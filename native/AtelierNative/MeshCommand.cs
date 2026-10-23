using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Assets.Exports.StaticMesh;
using CUE4Parse_Conversion;
using CUE4Parse_Conversion.Meshes;

namespace Atelier.Native;

/// <summary>
/// One-shot mesh export to glTF (.glb), the former AtelierMesh. Defaults match it exactly:
/// first LOD only, morph targets included.
/// </summary>
static class MeshCommand
{
    public static int Run(string[] args)
    {
        try
        {
            var options = GameProvider.Options(args);
            using var provider = GameProvider.Open(options["paks"], options["aes"], options.GetValueOrDefault("usmap"));
            var saved = Export(provider, options["asset"], options["out"],
                allLods: options.GetValueOrDefault("lods", "first") == "all",
                morphs: options.GetValueOrDefault("morphs", "1") != "0");
            Console.WriteLine("OK " + saved);
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("ERROR: " + error.Message);
            return 1;
        }
    }

    /// <summary>Export one mesh into <paramref name="outDir"/>; returns the written .glb path.</summary>
    public static string Export(CUE4Parse.FileProvider.AbstractFileProvider provider, string asset, string outDir,
        bool allLods, bool morphs)
    {
        var mesh = provider.LoadPackageObject(asset);
        var exportOptions = new ExporterOptions
        {
            MeshFormat = EMeshFormat.Gltf2,
            LodFormat = allLods ? ELodFormat.AllLods : ELodFormat.FirstLod,
            ExportMaterials = false,
            ExportMorphTargets = morphs,
        };
        MeshExporter exporter = mesh switch
        {
            USkeletalMesh skeletal => new MeshExporter(skeletal, exportOptions),
            UStaticMesh stationary => new MeshExporter(stationary, exportOptions),
            _ => throw new InvalidDataException("not a mesh: " + (mesh?.GetType().Name ?? "null")),
        };
        // Write the converted LODs ourselves. The pinned exporter's TryWriteToDir starts an
        // unawaited File.WriteAllBytesAsync, so a caller (or this process exiting) can read a
        // half-written .glb. Same paths as TryWriteToDir: <outDir>/<package path>.glb.
        Directory.CreateDirectory(outDir);
        string savedFilePath = "";
        foreach (var lod in exporter.MeshLods)
        {
            if (lod.FileData.Length == 0) continue;
            var relative = lod.FileName.TrimStart('/');
            savedFilePath = Path.Combine(outDir, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(savedFilePath)!);
            File.WriteAllBytes(savedFilePath, lod.FileData);
        }
        if (savedFilePath.Length == 0)
            throw new InvalidDataException("export failed");
        return savedFilePath;
    }
}
