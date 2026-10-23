using System.Text.Json;
using CUE4Parse.UE4.Assets.Exports.Animation;
using CUE4Parse.UE4.Assets.Exports.SkeletalMesh;
using CUE4Parse.UE4.Readers;
using CUE4Parse.UE4.Versions;

namespace Atelier.Native;

/// <summary>Independent CUE4Parse reading of a morph-target buffer Atelier wrote (verification only).</summary>
static class MorphCheckCommand
{
    public static int Run(string[] args)
    {
        if (args.Length != 2)
        {
            Console.Error.WriteLine("usage: AtelierNative morph-check <buffer.bin> <out.json>");
            return 2;
        }
        using var reader = new FByteArchive("Morph buffer", File.ReadAllBytes(args[0]), new VersionContainer(EGame.GAME_MarvelRivals));
        var buffer = new FMorphTargetVertexInfoBuffers(reader);
        var targets = new List<object>();
        for (int index = 0; index < buffer.BatchesPerMorph.Length; index++)
        {
            var target = new FMorphTargetLODModel(buffer, index, []);
            targets.Add(new
            {
                indices = target.Vertices.Select(v => v.SourceIdx).ToArray(),
                deltas = target.Vertices.Select(v => new[] { v.PositionDelta.X, v.PositionDelta.Y, v.PositionDelta.Z,
                    v.TangentZDelta.X, v.TangentZDelta.Y, v.TangentZDelta.Z }).ToArray(),
            });
        }
        File.WriteAllText(args[1], JsonSerializer.Serialize(new { targets, position_precision = buffer.PositionPrecision,
            tangent_precision = buffer.TangentZPrecision, consumed = reader.Position }));
        Console.WriteLine($"CUE4PARSE_MORPH_OK targets={targets.Count} batches={buffer.NumTotalBatches}");
        return 0;
    }
}
