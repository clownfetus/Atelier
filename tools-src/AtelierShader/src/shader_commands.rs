// Included inside the pinned upstream shader_library module. Its serializers,
// group decompression and loose-library format remain the source of truth.

const ATELIER_MAX_GROUP: usize = 64 * 1024 * 1024;

struct AtelierHeader {
    header: FIoStoreShaderCodeArchiveHeader,
    // Index -> (group index, start, size), derived without reading group payloads.
    ranges: Vec<(usize, usize, usize)>,
}

fn atelier_bounded_header(bytes: &[u8]) -> anyhow::Result<()> {
    if bytes.len() > 256 * 1024 * 1024 { bail!("Shader header exceeds the supported limit"); }
    let mut cursor = Cursor::new(bytes);
    let version: u32 = cursor.de()?;
    if version != 1 { bail!("Unsupported IoStore shader library version"); }
    // Bound every array before upstream deserialization allocates its entries.
    for width in [20u64, 20, 12, 8, 8, 16, 4] {
        let count: u32 = cursor.de()?;
        let end = cursor.position().checked_add(u64::from(count) * width)
            .ok_or_else(|| anyhow!("Shader header array overflow"))?;
        if end > bytes.len() as u64 { bail!("Truncated shader header array"); }
        cursor.set_position(end);
    }
    if cursor.position() != bytes.len() as u64 { bail!("Unexpected trailing shader header data"); }
    Ok(())
}

impl AtelierHeader {
    fn read(store: &dyn IoStoreTrait, id: FIoChunkId) -> anyhow::Result<Self> {
        Self::from_bytes(&store.read(id)?)
    }

    fn from_bytes(bytes: &[u8]) -> anyhow::Result<Self> {
        atelier_bounded_header(bytes)?;
        let mut cursor = Cursor::new(bytes);
        let _: u32 = cursor.de()?;
        let header = FIoStoreShaderCodeArchiveHeader::deserialize(&mut cursor, EIoStoreShaderLibraryVersion::Initial)?;
        if header.shader_entries.len() != header.shader_hashes.len() ||
            header.shader_map_entries.len() != header.shader_map_hashes.len() ||
            header.shader_group_entries.len() != header.shader_group_chunk_ids.len() {
            bail!("Inconsistent shader header array lengths");
        }
        let mut ranges = vec![(usize::MAX, 0, 0); header.shader_entries.len()];
        for (group_index, group) in header.shader_group_entries.iter().enumerate() {
            if group.num_shaders == 0 || group.uncompressed_size as usize > ATELIER_MAX_GROUP ||
                group.compressed_size == 0 || group.compressed_size > group.uncompressed_size {
                bail!("Invalid shader group size");
            }
            let indices = atelier_indices(&header.shader_indices, group.shader_indices_offset, group.num_shaders)?;
            let mut offsets = Vec::with_capacity(indices.len());
            for &index in indices {
                let index = index as usize;
                let entry = header.shader_entries.get(index).ok_or_else(|| anyhow!("Shader group index out of range"))?;
                if entry.shader_group_index() != group_index { bail!("Conflicting shader group index"); }
                offsets.push((entry.shader_uncompressed_offset_in_group(), index));
            }
            offsets.sort_unstable();
            if offsets[0].0 != 0 { bail!("Shader group has an invalid first offset"); }
            for (position, &(start, index)) in offsets.iter().enumerate() {
                let end = offsets.get(position + 1).map(|x| x.0).unwrap_or(group.uncompressed_size as usize);
                if start >= end || end > group.uncompressed_size as usize || ranges[index].0 != usize::MAX {
                    bail!("Invalid or duplicate shader range");
                }
                ranges[index] = (group_index, start, end - start);
            }
        }
        if ranges.iter().any(|r| r.0 == usize::MAX) { bail!("Shader is missing from its group"); }
        for map in &header.shader_map_entries {
            for &index in atelier_indices(&header.shader_indices, map.shader_indices_offset, map.num_shaders)? {
                if index as usize >= ranges.len() { bail!("Shader map index out of range"); }
            }
        }
        Ok(Self { header, ranges })
    }

    fn group(&self, store: &dyn IoStoreTrait, index: usize) -> anyhow::Result<Vec<u8>> {
        let entry = self.header.shader_group_entries.get(index).ok_or_else(|| anyhow!("Shader group out of range"))?;
        let bytes = store.read_raw(self.header.shader_group_chunk_ids[index])?;
        if bytes.len() != entry.compressed_size as usize { bail!("Shader group stored size does not match its header"); }
        if entry.compressed_size == entry.uncompressed_size { return Ok(bytes); }
        let mut method = None;
        let bytes = decompress_shader_code(&bytes, &mut method, entry.uncompressed_size as usize)?;
        if bytes.len() != entry.uncompressed_size as usize { bail!("Invalid decompressed shader group size"); }
        Ok(bytes)
    }

    fn shader(&self, store: &dyn IoStoreTrait, index: usize) -> anyhow::Result<Vec<u8>> {
        let &(group, start, size) = self.ranges.get(index).ok_or_else(|| anyhow!("Shader index out of range"))?;
        Ok(self.group(store, group)?[start..start + size].to_vec())
    }
}

fn atelier_indices(indices: &[u32], start: u32, count: u32) -> anyhow::Result<&[u32]> {
    let end = (start as usize).checked_add(count as usize).ok_or_else(|| anyhow!("Shader index array overflow"))?;
    indices.get(start as usize..end).ok_or_else(|| anyhow!("Shader index array out of range"))
}

fn atelier_library_name(path: &str) -> anyhow::Result<String> {
    let normalized = path.replace('\\', "/");
    let filename = normalized.rsplit('/').next().ok_or_else(|| anyhow!("Missing shader library name"))?;
    let name = filename.strip_suffix(".ushaderbytecode").ok_or_else(|| anyhow!("Invalid shader library extension"))?;
    if !name.starts_with("ShaderArchive-") || name.len() > 240 ||
        !name.bytes().all(|c| c.is_ascii_alphanumeric() || b"-_.".contains(&c)) {
        bail!("Unsafe shader library name");
    }
    Ok(name.to_string())
}

pub fn atelier_libraries(store: &dyn IoStoreTrait) -> anyhow::Result<Vec<(String, FIoChunkId)>> {
    let mut libraries = Vec::new();
    for chunk in store.chunks() {
        if chunk.id().get_chunk_type() == EIoChunkType::ShaderCodeLibrary {
            let path = chunk.path().ok_or_else(|| anyhow!("Shader library is missing its path"))?;
            libraries.push((atelier_library_name(&path)?, chunk.id()));
        }
    }
    libraries.sort_by(|a, b| a.0.cmp(&b.0));
    if libraries.windows(2).any(|pair| pair[0].0 == pair[1].0) { bail!("Ambiguous shader library name"); }
    Ok(libraries)
}

fn atelier_find(store: &dyn IoStoreTrait, name: &str) -> anyhow::Result<FIoChunkId> {
    atelier_libraries(store)?.into_iter().find(|p| p.0 == name).map(|p| p.1)
        .ok_or_else(|| anyhow!("Shader library not found"))
}

pub fn atelier_index<W: Write>(store: &dyn IoStoreTrait, id: FIoChunkId, name: &str, output: &mut W) -> anyhow::Result<usize> {
    let library = AtelierHeader::read(store, id)?;
    let header = &library.header;
    writeln!(output, "{{\n  \"library\": {},\n  \"count\": {},\n  \"shaders\": [", serde_json::to_string(name)?, library.ranges.len())?;
    for (index, entry) in header.shader_entries.iter().enumerate() {
        let frequency = entry.shader_frequency();
        let hash = hex::encode(header.shader_hashes[index].0);
        let file = format!("{index:05}_freq{frequency:02}_{}.dxil", &hash[..16]);
        writeln!(output, "    {{\"index\": {index}, \"frequency\": {frequency}, \"hash\": \"{hash}\", \"size\": {}, \"file\": \"{file}\"}}{}",
            library.ranges[index].2, if index + 1 == library.ranges.len() { "" } else { "," })?;
    }
    writeln!(output, "  ]\n}}")?;
    Ok(library.ranges.len())
}

pub fn atelier_extract(store: &dyn IoStoreTrait, name: &str, index: usize) -> anyhow::Result<Vec<u8>> {
    let id = atelier_find(store, name)?;
    AtelierHeader::read(store, id)?.shader(store, index)
}

fn atelier_dxbc(bytes: &[u8]) -> anyhow::Result<(usize, usize)> {
    let offset = bytes.windows(4).position(|b| b == b"DXBC").ok_or_else(|| anyhow!("Shader has no DXBC container"))?;
    let u32_at = |position: usize| -> anyhow::Result<usize> {
        Ok(u32::from_le_bytes(bytes.get(position..position + 4).ok_or_else(|| anyhow!("Truncated DXBC header"))?.try_into()?) as usize)
    };
    let size = u32_at(offset + 24)?;
    let count = u32_at(offset + 28)?;
    if size < 32 || size > ATELIER_MAX_GROUP || count == 0 || count > 4096 || 32 + count * 4 > size ||
        offset.checked_add(size).is_none_or(|end| end > bytes.len()) { bail!("Invalid DXBC container size"); }
    let mut parts = Vec::with_capacity(count);
    for part in 0..count {
        let start = u32_at(offset + 32 + part * 4)?;
        if start < 32 + count * 4 || start + 8 > size { bail!("Invalid DXBC part offset"); }
        let end = start.checked_add(8 + u32_at(offset + start + 4)?).ok_or_else(|| anyhow!("DXBC part size overflow"))?;
        if end > size { bail!("Truncated DXBC part"); }
        parts.push((start, end));
    }
    parts.sort_unstable();
    if parts.windows(2).any(|p| p[0].1 > p[1].0) { bail!("Overlapping DXBC parts"); }
    Ok((offset, size))
}

pub fn atelier_patch(store: &dyn IoStoreTrait, name: &str, index: usize, replacement: &[u8], output: &std::path::Path) -> anyhow::Result<()> {
    let id = atelier_find(store, name)?;
    let library = AtelierHeader::read(store, id)?;
    let original = library.shader(store, index)?;
    let (old_offset, old_size) = atelier_dxbc(&original)?;
    let (new_offset, new_size) = atelier_dxbc(replacement)?;
    if replacement[..new_offset] != original[..old_offset] ||
        replacement[new_offset + new_size..] != original[old_offset + old_size..] {
        bail!("Replacement changed the Unreal shader wrapper");
    }
    let io = &library.header;
    let mut loose = FShaderLibraryHeader {
        // Preserve engine lookup identities. Group IDs are rebuilt by upstream pack.
        shader_map_hashes: io.shader_map_hashes.clone(), shader_hashes: io.shader_hashes.clone(),
        shader_indices: io.shader_indices.clone(), ..Default::default()
    };
    let mut position = 0u64;
    for (shader_index, entry) in io.shader_entries.iter().enumerate() {
        let size = if shader_index == index { replacement.len() } else { library.ranges[shader_index].2 };
        let size = u32::try_from(size)?;
        loose.shader_entries.push(FShaderCodeEntry { offset: position, size, uncompressed_size: size, frequency: entry.shader_frequency() });
        position = position.checked_add(u64::from(size)).ok_or_else(|| anyhow!("Loose shader library size overflow"))?;
    }
    // Exact per-shader preload ranges support shared shaders and changed code sizes.
    for map in &io.shader_map_entries {
        let first_preload_index = u32::try_from(loose.preload_entries.len())?;
        for &shader in atelier_indices(&io.shader_indices, map.shader_indices_offset, map.num_shaders)? {
            let entry = &loose.shader_entries[shader as usize];
            loose.preload_entries.push(FFileCachePreloadEntry { offset: i64::try_from(entry.offset)?, size: i64::from(entry.size) });
        }
        loose.shader_map_entries.push(FShaderMapEntry { shader_indices_offset: map.shader_indices_offset,
            num_shaders: map.num_shaders, first_preload_index, num_preload_entries: map.num_shaders });
    }
    let path = store.chunk_path(id).ok_or_else(|| anyhow!("Missing shader library path"))?;
    let path = path.replace('\\', "/");
    let path = path.strip_prefix("../../../").unwrap_or(&path);
    let path = atelier_relative_path(path)?;
    let target = output.join(&path);
    std::fs::create_dir_all(target.parent().ok_or_else(|| anyhow!("Missing output directory"))?)?;
    let mut file = std::fs::File::create(&target)?;
    file.ser(&2u32)?;
    loose.serialize(&mut file)?;
    let code_start = file.stream_position()?;
    // Keep only a group in memory; never materialize the 12GB shader archive.
    for group_index in 0..io.shader_group_entries.len() {
        let bytes = library.group(store, group_index)?;
        let group = io.shader_group_entries[group_index];
        for &shader in atelier_indices(&io.shader_indices, group.shader_indices_offset, group.num_shaders)? {
            let shader = shader as usize;
            let entry = &loose.shader_entries[shader];
            file.seek(SeekFrom::Start(code_start + entry.offset))?;
            let (_, start, size) = library.ranges[shader];
            file.write_all(if shader == index { replacement } else { &bytes[start..start + size] })?;
        }
    }
    file.sync_all()?;
    let metadata = atelier_metadata_path(&path)?;
    // This output contains only a shader library; no converted packages need associations.
    std::fs::write(output.join(metadata), b"{\"ShaderCodeToAssets\":[]}\n")?;
    Ok(())
}

fn atelier_metadata_path(path: &std::path::Path) -> anyhow::Result<std::path::PathBuf> {
    // Upstream's UEPath is Unix-style even when the output is on Windows.
    let path = path.to_str().ok_or_else(|| anyhow!("Invalid shader path"))?.replace('\\', "/");
    atelier_relative_path(&get_shader_asset_info_filename_from_library_filename(&path)?)
}

pub(crate) fn atelier_safe_relative_path(value: &str) -> anyhow::Result<std::path::PathBuf> {
    let value = value.replace('\\', "/");
    if value.is_empty() || value.starts_with('/') || value.contains(':') ||
        value.split('/').any(|part| part.is_empty() || part == "." || part == "..") {
        bail!("Unsafe output path in shader library");
    }
    Ok(value.split('/').collect())
}

fn atelier_relative_path(value: &str) -> anyhow::Result<std::path::PathBuf> {
    atelier_safe_relative_path(value)
}

#[cfg(test)]
mod atelier_tests {
    use super::*;

    fn header_bytes(header: &FIoStoreShaderCodeArchiveHeader) -> Vec<u8> {
        let mut bytes = 1u32.to_le_bytes().to_vec();
        header.serialize(&mut bytes, EIoStoreShaderLibraryVersion::Initial).unwrap();
        bytes
    }

    #[test]
    fn rejects_truncated_and_hostile_array_counts_before_allocation() {
        let mut bytes = header_bytes(&FIoStoreShaderCodeArchiveHeader::default());
        for length in 0..bytes.len() { assert!(AtelierHeader::from_bytes(&bytes[..length]).is_err()); }
        bytes[4..8].copy_from_slice(&u32::MAX.to_le_bytes());
        assert!(AtelierHeader::from_bytes(&bytes).is_err());
    }

    #[test]
    fn derives_ranges_without_group_reads_and_rejects_conflicts() {
        let mut header = FIoStoreShaderCodeArchiveHeader::default();
        header.shader_hashes = vec![FSHAHash::default(); 2];
        header.shader_entries = vec![FIoStoreShaderCodeEntry::new(0, 0, 5), FIoStoreShaderCodeEntry::new(0, 12, 3)];
        header.shader_indices = vec![1, 0];
        header.shader_group_entries = vec![FIoStoreShaderGroupEntry { shader_indices_offset: 0, num_shaders: 2, uncompressed_size: 30, compressed_size: 20 }];
        header.shader_group_chunk_ids = vec![FIoChunkIdRaw { id: [0; 12] }];
        assert_eq!(AtelierHeader::from_bytes(&header_bytes(&header)).unwrap().ranges, vec![(0, 0, 12), (0, 12, 18)]);
        header.shader_indices = vec![0, 0];
        assert!(AtelierHeader::from_bytes(&header_bytes(&header)).is_err());
        header.shader_indices = vec![0, 9];
        assert!(AtelierHeader::from_bytes(&header_bytes(&header)).is_err());
    }

    #[test]
    fn rejects_escaping_library_names_and_paths_on_every_host() {
        for path in ["../outside", "C:/outside", "\\\\server\\share", "/absolute", "a/../b", "a//b"] {
            assert!(atelier_relative_path(path).is_err(), "{path}");
        }
        assert!(atelier_relative_path("Marvel/Content/library.ushaderbytecode").is_ok());
        assert!(atelier_library_name("ShaderArchive-Global-PCD3D_SM6-PCD3D_SM6.ushaderbytecode").is_ok());
        assert!(atelier_library_name("ShaderArchive-C:bad.ushaderbytecode").is_err());
    }

    #[test]
    fn rejects_truncated_dxbc_part_tables_and_invalid_spans() {
        let mut bytes = b"DXBC".to_vec();
        bytes.resize(44, 0);
        bytes[24..28].copy_from_slice(&44u32.to_le_bytes());
        bytes[28..32].copy_from_slice(&1u32.to_le_bytes());
        bytes[32..36].copy_from_slice(&36u32.to_le_bytes());
        assert_eq!(atelier_dxbc(&bytes).unwrap(), (0, 44));
        bytes[40..44].copy_from_slice(&u32::MAX.to_le_bytes());
        assert!(atelier_dxbc(&bytes).is_err());
        assert!(atelier_dxbc(&bytes[..30]).is_err());
    }

    #[test]
    fn concurrent_asset_writes_preserve_every_file_in_shared_directories() {
        use crate::FileWriterTrait;
        use std::sync::{Arc, Barrier};
        let output = tempfile::tempdir().unwrap();
        let writer = Arc::new(crate::FSFileWriter::new(output.path()));
        let barrier = Arc::new(Barrier::new(32));
        let threads = (0..32u8).map(|index| {
            let writer = writer.clone();
            let barrier = barrier.clone();
            std::thread::spawn(move || {
                barrier.wait();
                writer.write_file(format!("Marvel/Content/Shared/asset-{index}.uasset"), false, vec![index]).unwrap();
            })
        }).collect::<Vec<_>>();
        for thread in threads { thread.join().unwrap(); }
        for index in 0..32u8 {
            assert_eq!(std::fs::read(output.path().join(format!("Marvel/Content/Shared/asset-{index}.uasset"))).unwrap(), vec![index]);
        }
    }

    #[test]
    fn shader_asset_metadata_stays_beside_the_library_on_every_host() {
        let path: std::path::PathBuf = ["Marvel", "Content", "ShaderArchive-Global-PCD3D_SM6-PCD3D_SM6.ushaderbytecode"].iter().collect();
        let metadata = atelier_metadata_path(&path).unwrap();
        assert_eq!(metadata.parent(), path.parent());
        assert_eq!(metadata.file_name().unwrap(), "ShaderAssetInfo-Global-PCD3D_SM6-PCD3D_SM6.assetinfo.json");
    }
}
