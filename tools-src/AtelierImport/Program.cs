using System.Diagnostics;
using System.Text.Json;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports;
using CUE4Parse.UE4.Assets.Exports.Material;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Assets.Objects;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;
using CUE4Parse_Conversion;
using CUE4Parse_Conversion.Meshes;
using CUE4Parse_Conversion.Textures;
using SixLabors.ImageSharp;
using SixLabors.ImageSharp.Formats.Png;
using SixLabors.ImageSharp.PixelFormats;

// A private, parent-owned import server. The game provider is initialized once;
// requests use inherited pipes, never a public HTTP listener or command-line key.
// Provider use is serial because package deserialization is not thread safe.
var protocol = Console.Out;
Console.SetOut(Console.Error);
using var service = new ImportService();
while (Console.ReadLine() is { } line)
{
    string? id = null;
    try
    {
        if (line.Length > 65536) throw new InvalidDataException("Import request is too large");
        using var document = JsonDocument.Parse(line);
        var request = document.RootElement;
        id = request.GetProperty("id").GetString();
        var timer = Stopwatch.StartNew();
        var data = service.Handle(request);
        if (request.GetProperty("action").GetString() == "mesh")
            GC.Collect(2, GCCollectionMode.Aggressive, true, true);
        protocol.WriteLine(JsonSerializer.Serialize(new { id, ok = true, data, elapsed_ms = timer.ElapsedMilliseconds }));
    }
    catch (Exception error)
    {
        Console.Error.WriteLine($"[import] {error.GetType().Name}: {error.Message}");
        protocol.WriteLine(JsonSerializer.Serialize(new { id, ok = false, error = error.Message }));
    }
    protocol.Flush();
}

sealed class ImportService : IDisposable
{
    DefaultFileProvider? provider;
    string cache = "";
    int requests;
    readonly Dictionary<string, object> materials = new(StringComparer.OrdinalIgnoreCase);

    public object Handle(JsonElement request)
    {
        var action = request.GetProperty("action").GetString();
        if (action == "initialize")
        {
            if (provider != null) throw new InvalidOperationException("Import server is already initialized");
            cache = Path.GetFullPath(request.GetProperty("cache_root").GetString()!);
            Directory.CreateDirectory(cache);
            var paks = request.GetProperty("paks").GetString()!;
            var reader = new DefaultFileProvider(paks, SearchOption.TopDirectoryOnly,
                new VersionContainer(EGame.GAME_MarvelRivals), StringComparer.OrdinalIgnoreCase);
            try
            {
                // Register archives directly so ~mods, loose files and the known
                // top-level Galacta loader never shadow pristine game packages.
                foreach (var file in new DirectoryInfo(paks).EnumerateFiles("*", SearchOption.TopDirectoryOnly))
                    if ((file.Extension.Equals(".pak", StringComparison.OrdinalIgnoreCase)
                         || file.Extension.Equals(".utoc", StringComparison.OrdinalIgnoreCase))
                        && !Path.GetFileNameWithoutExtension(file.Name).Equals("!projectgalacta_9999999_p", StringComparison.OrdinalIgnoreCase))
                        reader.RegisterVfs(file);
                reader.SubmitKey(new FGuid(), new FAesKey(request.GetProperty("aes").GetString()!));
                reader.MappingsContainer = new FileUsmapTypeMappingsProvider(request.GetProperty("usmap").GetString()!);
                provider = reader;
            }
            catch { reader.Dispose(); throw; }
            return new { protocol = 1, pid = Environment.ProcessId, initializations = 1, files = reader.Files.Count };
        }
        if (provider == null) throw new InvalidOperationException("Initialize the import server first");
        requests++;
        return action switch
        {
            "mesh" => Mesh(request.GetProperty("asset").GetString()!),
            "material" => Material(request.GetProperty("asset").GetString()!),
            "texture" => Texture(request.GetProperty("asset").GetString()!),
            "stats" => new { pid = Environment.ProcessId, initializations = 1, requests, files = provider.Files.Count,
                private_bytes = Process.GetCurrentProcess().PrivateMemorySize64, managed_bytes = GC.GetTotalMemory(false) },
            _ => throw new InvalidDataException("Unknown import action")
        };
    }

    static string Asset(string value)
    {
        var parts = value.Replace('\\', '/').Split('/');
        if (parts.Length < 2 || parts.Any(p => p.Length == 0 || p is "." or ".." || p.EndsWith('.') || p.EndsWith(' ')
            || p.Any(c => char.IsControl(c) || ":*?\"<>|".Contains(c))))
            throw new InvalidDataException("Invalid game asset path");
        return string.Join('/', parts);
    }

    string Target(string kind, string asset, string extension)
    {
        asset = Asset(asset);
        var root = Path.Combine(cache, kind);
        var target = Path.GetFullPath(Path.Combine(root, asset + extension));
        if (!target.StartsWith(Path.GetFullPath(root) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("Import output must remain inside its cache");
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        return target;
    }

    static void Publish(string target, byte[] bytes)
    {
        string temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try { File.WriteAllBytes(temporary, bytes); File.Move(temporary, target, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    static string? GameRel(ResolvedObject? reference)
    {
        var path = reference?.GetPathName();
        if (path == null) return null;
        path = path.Split('.')[0];
        if (path.StartsWith("/Game/Marvel/", StringComparison.OrdinalIgnoreCase)) return path[13..];
        if (path.StartsWith("/Marvel_LQ/", StringComparison.OrdinalIgnoreCase)) return "Marvel_LQ/" + path[11..];
        return null;
    }

    object Mesh(string asset)
    {
        asset = Asset(asset);
        var mesh = provider!.LoadPackageObject(asset);
        var options = new ExporterOptions { MeshFormat = EMeshFormat.Gltf2, LodFormat = ELodFormat.FirstLod,
            ExportMaterials = false, ExportMorphTargets = false };
        // Preview idles animate bones, not facial morphs. Portable Blender exports
        // retain their separate complete geometry/morph pipeline.
        MeshExporter exporter = mesh switch
        {
            USkeletalMesh skeletal => new MeshExporter(skeletal, options),
            UStaticMesh stationary => new MeshExporter(stationary, options),
            _ => throw new InvalidDataException("The selected asset is not a mesh")
        };
        var output = exporter.MeshLods.FirstOrDefault() ?? throw new InvalidDataException("The mesh has no renderable detail level");
        var target = Target("gltf", asset, ".glb");
        // TryWriteToDir starts an unawaited asynchronous write in the pinned
        // exporter. Reading/deleting its staging file races that writer on
        // Windows. The first-LOD GLB is already complete in FileData; publish
        // those exact bytes synchronously before returning the cache path.
        if (output.FileData.Length == 0) throw new InvalidDataException("Mesh export failed");
        Publish(target, output.FileData);
        object[] slots = mesh switch
        {
            USkeletalMesh sk => sk.SkeletalMaterials.Select((material, index) => new { index, slot = material.MaterialSlotName.Text,
                mi = GameRel(material.Material), via = "imports", gameplay_tags = Array.Empty<string>() }).ToArray(),
            UStaticMesh sm => (sm.StaticMaterials ?? []).Select((material, index) => new { index, slot = material.MaterialSlotName.Text,
                mi = GameRel(material.MaterialInterface), via = "imports", gameplay_tags = Array.Empty<string>() }).ToArray(),
            _ => []
        };
        var metadata = new { version = 1, asset, slots, preview_morphs = false };
        Publish(Target("meshes", asset, ".json"), JsonSerializer.SerializeToUtf8Bytes(metadata));
        return new { path = target, metadata };
    }

    object Material(string asset)
    {
        asset = Asset(asset);
        if (materials.TryGetValue(asset, out var hit)) return hit;
        var material = provider!.LoadPackageObject(asset) as UMaterialInstanceConstant
            ?? throw new InvalidDataException("The selected asset is not a material instance");
        var textures = material.TextureParameterValues.Where(p => p.ParameterValue != null)
            .Select(p => (p.Name, reference: p.ParameterValue.ResolvedObject))
            .Where(p => GameRel(p.reference) != null).ToDictionary(p => p.Name, p => GameRel(p.reference)!);
        var classes = material.TextureParameterValues.Where(p => p.ParameterValue != null && textures.ContainsKey(p.Name))
            .ToDictionary(p => p.Name, p => p.ParameterValue.ResolvedObject?.Class?.Name.Text ?? "");
        var parent = material.GetOrDefault<ResolvedObject>("Parent");
        var parentName = parent?.Name.Text ?? "";
        var scalars = material.ScalarParameterValues.Select(p => new { name = p.Name, value = Math.Round((double)p.ParameterValue, 5) }).ToArray();
        var overrides = material.GetOrDefault<FStructFallback>("BasePropertyOverrides");
        string? blend = material.BasePropertyOverrides == null ? null : (byte)material.BasePropertyOverrides.BlendMode switch
            { 2 => "BLEND_TranslucentGreyTransmittance", 4 => "BLEND_ColoredTransmittanceOnly", _ => material.BasePropertyOverrides.BlendMode.ToString() };
        var surface = new { blend_mode = blend
                ?? (parentName.Contains("translucent", StringComparison.OrdinalIgnoreCase) ? "BLEND_Translucent" : "BLEND_Opaque"),
            two_sided = overrides?.GetOrDefault("TwoSided", false) ?? false,
            opacity = Math.Clamp(scalars.FirstOrDefault(p => p.name.Equals("OpacityMultiplier", StringComparison.OrdinalIgnoreCase))?.value
                ?? scalars.FirstOrDefault(p => p.name.Equals("Opacity", StringComparison.OrdinalIgnoreCase))?.value ?? 1, 0, 1),
            mask_clip = Math.Clamp((double)(material.BasePropertyOverrides?.OpacityMaskClipValue ?? .3333f), 0, 1),
            parent = parentName, parent_path = GameRel(parent) };
        // The existing editor omits zero-mask LinearColor structs (no editable
        // serialized payload). Keep its parameter and tint contract unchanged.
        var result = new { colors = material.VectorParameterValues.Where(p => p.ParameterValue is { } v &&
                (v.R != 0 || v.G != 0 || v.B != 0 || v.A != 0)).Select(p => new {
            name = p.Name, rgba = new[] {p.ParameterValue!.Value.R, p.ParameterValue.Value.G, p.ParameterValue.Value.B, p.ParameterValue.Value.A}
                .Select(v => Math.Round((double)v, 5)).ToArray() }).ToArray(), scalars, textures, texture_classes = classes,
            surface, material_source = "" };
        if (materials.Count >= 512) materials.Clear();
        materials[asset] = result;
        return result;
    }

    object Texture(string asset)
    {
        asset = Asset(asset);
        var target = Target("textures", asset, ".png");
        if (File.Exists(target)) return new { path = target };
        var texture = provider!.LoadPackageObject(asset) as UTexture
            ?? throw new InvalidDataException("The selected asset is not a texture");
        var format = texture.PlatformData.PixelFormat.ToString().Replace("PF_", "");
        if (format is "DXT1" or "DXT5" or "BC4" or "BC5" or "BC6H" or "BC7")
        {
            // Keep original compressed blocks. A decoder's one-byte rounding
            // difference can cross a dye mask's quantized region boundary.
            // The parent uses its existing DDS/Pillow decoder for pixel parity.
            var mip = texture.GetFirstMip() ?? throw new InvalidDataException("Texture mip is unavailable");
            if (mip.SizeX < 1 || mip.SizeY < 1 || mip.SizeX > 16384 || mip.SizeY > 16384
                || mip.SizeX < 16 && texture.PlatformData.SizeX > 64 || mip.SizeY < 16 && texture.PlatformData.SizeY > 64)
                throw new InvalidDataException("Texture mip requires the compatibility decoder");
            var data = mip.BulkData?.Data ?? throw new InvalidDataException("Texture block data is unavailable");
            var bytesPerBlock = format is "DXT1" or "BC4" ? 8 : 16;
            var size = Math.Max(1, (mip.SizeX + 3) / 4) * Math.Max(1, (mip.SizeY + 3) / 4) * bytesPerBlock;
            if (data.Length != size) throw new InvalidDataException("Texture blocks require the compatibility decoder");
            var blocks = Target("blocks", asset, ".bin");
            Publish(blocks, data);
            return new { path = blocks, encoding = "blocks", format, width = mip.SizeX, height = mip.SizeY };
        }
        var decoded = texture.Decode() ?? throw new InvalidDataException("Texture pixels are unavailable");
        if (decoded.Width < 1 || decoded.Height < 1 || decoded.Width > 16384 || decoded.Height > 16384
            || decoded.Width < 16 && texture.PlatformData.SizeX > 64 || decoded.Height < 16 && texture.PlatformData.SizeY > 64)
            throw new InvalidDataException("Texture mip requires the compatibility decoder");
        using var stream = new MemoryStream();
        var encoder = new PngEncoder { CompressionLevel = PngCompressionLevel.Level1 };
        if (decoded.Data.Length == decoded.Width * decoded.Height * 4)
        {
            if (decoded.PixelFormat == EPixelFormat.PF_R8G8B8A8)
            { using var image = Image.LoadPixelData<Rgba32>(decoded.Data, decoded.Width, decoded.Height); image.Save(stream, encoder); }
            else
            { using var image = Image.LoadPixelData<Bgra32>(decoded.Data, decoded.Width, decoded.Height); image.Save(stream, encoder); }
        }
        else if (decoded.Data.Length == decoded.Width * decoded.Height)
        { using var image = Image.LoadPixelData<L8>(decoded.Data, decoded.Width, decoded.Height); image.Save(stream, encoder); }
        else throw new InvalidDataException("Texture pixel format requires the compatibility decoder");
        Publish(target, stream.ToArray());
        return new { path = target, width = decoded.Width, height = decoded.Height };
    }

    public void Dispose() => provider?.Dispose();
}
