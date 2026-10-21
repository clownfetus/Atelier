// Independent readback through the exact pinned CUE4Parse assemblies.
// Runtime keys travel over stdin and never appear in arguments or results.
using System.Security.Cryptography;
using System.Runtime.InteropServices;
using System.Text.Json;
using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Assets;
using CUE4Parse.UE4.Assets.Exports.Texture;
using CUE4Parse.UE4.Assets.Exports.Material;
using Serilog;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;

var protocol = Console.Out;
Console.SetOut(Console.Error);
Log.Logger = new LoggerConfiguration().MinimumLevel.Warning()
    .WriteTo.Console(standardErrorFromLevel: Serilog.Events.LogEventLevel.Verbose).CreateLogger();
try
{
    using var request = JsonDocument.Parse(Console.In.ReadToEnd());
    var input = request.RootElement;
    using var provider = new DefaultFileProvider(input.GetProperty("paks").GetString()!,
        SearchOption.TopDirectoryOnly, new VersionContainer(EGame.GAME_MarvelRivals), StringComparer.OrdinalIgnoreCase);
    foreach (var file in new DirectoryInfo(input.GetProperty("paks").GetString()!).EnumerateFiles())
        if (file.Extension.Equals(".pak", StringComparison.OrdinalIgnoreCase) || file.Extension.Equals(".utoc", StringComparison.OrdinalIgnoreCase))
            provider.RegisterVfs(file);
    provider.SubmitKey(new FGuid(), new FAesKey(input.GetProperty("aes").GetString()!));
    provider.MappingsContainer = new FileUsmapTypeMappingsProvider(input.GetProperty("usmap").GetString()!);
    var results = new List<object>();
    foreach (var value in input.GetProperty("assets").EnumerateArray())
    {
        var selected = value.GetString()!;
        var path = provider.Files.Keys.Single(key => key.Replace('\\', '/').EndsWith('/'+selected+".uasset", StringComparison.OrdinalIgnoreCase));
        var obj = provider.LoadPackageObject(path[..^7]);
        if (obj is UMaterialInstanceConstant material)
        {
            var slots = input.TryGetProperty("material_slots", out var chosen) ? chosen.EnumerateArray()
                .Select(slot => slot.GetString()).ToHashSet() : null;
            var textures = material.TextureParameterValues.Where(p => slots == null || slots.Contains(p.Name)).Select(p => new {
                slot = p.Name, path = p.ParameterValue?.ResolvedObject?.GetPathName(),
                texture_class = p.ParameterValue?.ResolvedObject?.Class?.Name.Text }).ToArray();
            results.Add(new { asset = selected, texture_class = material.GetType().Name, textures });
            continue;
        }
        var texture = obj as UTextureCube ?? throw new InvalidDataException("Expected TextureCube");
        if (!texture.PlatformData.IsCubemap() || texture.PlatformData.GetNumSlices() != 6)
            throw new InvalidDataException("Expected six cube slices");
        var mips = new List<object>();
        foreach (var mip in texture.PlatformData.Mips)
        {
            var data = mip.BulkData?.Data ?? throw new InvalidDataException("Missing mip data");
            if (data.Length == 0 || data.Length % 6 != 0 || mip.SizeY != mip.SizeX * 6 || mip.SizeZ != 1)
                throw new InvalidDataException("Incomplete cube mip");
            var faceSize = data.Length / 6;
            var hashes = Enumerable.Range(0, 6).Select(index => Convert.ToHexString(
                SHA256.HashData(data.AsSpan(index * faceSize, faceSize))).ToLowerInvariant()).ToArray();
            float? minimum = null, maximum = null;
            if (texture.Format == EPixelFormat.PF_FloatRGBA)
            {
                var values = MemoryMarshal.Cast<byte, Half>(data);
                for (var index = 0; index < values.Length; index++)
                {
                    if (index % 4 == 3) continue;
                    var number = (float)values[index];
                    if (!float.IsFinite(number)) throw new InvalidDataException("Nonfinite HDR pixels");
                    minimum = minimum.HasValue ? Math.Min(minimum.Value, number) : number;
                    maximum = maximum.HasValue ? Math.Max(maximum.Value, number) : number;
                }
            }
            mips.Add(new { width = mip.SizeX, height = mip.SizeY / 6, bytes = data.Length,
                face_sha256 = hashes, minimum, maximum });
        }
        results.Add(new { asset = value.GetString(), texture_class = texture.GetType().Name,
            format = texture.Format.ToString(), group = texture.LODGroup.ToString(), slices = texture.PlatformData.GetNumSlices(), mips });
    }
    protocol.WriteLine(JsonSerializer.Serialize(new { ok = true, results }));
}
catch (Exception error)
{
    var message = error.Message;
    if (message.Contains("aes", StringComparison.OrdinalIgnoreCase) || message.Contains("key", StringComparison.OrdinalIgnoreCase))
        message = "Texture reader input or key error";
    protocol.WriteLine(JsonSerializer.Serialize(new { ok = false, error = error.GetType().Name, message }));
    Environment.ExitCode = 1;
}
