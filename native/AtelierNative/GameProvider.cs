using CUE4Parse.Encryption.Aes;
using CUE4Parse.FileProvider;
using CUE4Parse.FileProvider.Objects;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Objects.Core.Misc;
using CUE4Parse.UE4.Versions;

namespace Atelier.Native;

/// <summary>
/// Opens the game's own containers only. Mods (~mods, loose files) and the Project Galacta loader
/// sit beside or below the Paks folder and would otherwise shadow pristine packages, which is how
/// a decode used to silently return someone's installed mod instead of the game asset.
/// </summary>
static class GameProvider
{
    const string GalactaLoader = "!projectgalacta_9999999_p";

    public static DefaultFileProvider Open(string paks, string aesHex, string? usmap)
    {
        var provider = new DefaultFileProvider(paks, SearchOption.TopDirectoryOnly,
            new VersionContainer(EGame.GAME_MarvelRivals), StringComparer.OrdinalIgnoreCase);
        try
        {
            foreach (var file in new DirectoryInfo(paks).EnumerateFiles("*", SearchOption.TopDirectoryOnly))
                if ((file.Extension.Equals(".pak", StringComparison.OrdinalIgnoreCase)
                     || file.Extension.Equals(".utoc", StringComparison.OrdinalIgnoreCase))
                    && !Path.GetFileNameWithoutExtension(file.Name).Equals(GalactaLoader, StringComparison.OrdinalIgnoreCase))
                    provider.RegisterVfs(file);
            provider.SubmitKey(new FGuid(), new FAesKey(aesHex));
            // CUE4Parse mounts containers concurrently. Its generic patch parser
            // gives Rivals' dotted build names (1.1.3962284, 1.1.3984769, ...)
            // the same priority, so completion order can select an older asset.
            // Its package-ID index also ignores read priority. Rebuild both from
            // one deterministic set before any packages are decoded, matching
            // atelier.index's filename ordering within each engine priority.
            var files = new Dictionary<string, GameFile>(StringComparer.OrdinalIgnoreCase);
            foreach (var reader in provider.MountedVfs.OrderBy(reader => reader.ReadOrder)
                         .ThenBy(reader => reader.Name, StringComparer.OrdinalIgnoreCase))
                foreach (var (path, file) in reader.Files)
                    files[path] = file;
            provider.Files.Clear();
            // A single index gives path and package-ID lookups the same winner.
            // Leave its priority at zero so VerifyCommand can mount a mod over it.
            provider.Files.AddFiles(files);
            if (!string.IsNullOrEmpty(usmap))
                provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap);
            return provider;
        }
        catch
        {
            provider.Dispose();
            throw;
        }
    }

    /// <summary>Whether CUE4Parse-Natives (ACL animation decompression) loaded beside the executable.</summary>
    public static bool NativesAvailable()
    {
        try { return CUE4Parse.Utils.CUE4ParseNatives.IsFeatureAvailable("ACL"); }
        catch { return false; }
    }

    public static Dictionary<string, string> Options(string[] args)
    {
        var options = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i + 1 < args.Length; i += 2)
            options[args[i].TrimStart('-')] = args[i + 1];
        return options;
    }
}
