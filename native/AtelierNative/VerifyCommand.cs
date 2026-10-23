using System.Text.Json;
using CUE4Parse.UE4.Assets.Exports;
using Serilog;
using Serilog.Core;
using Serilog.Events;

namespace Atelier.Native;

/// <summary>
/// Read a built mod back the way the game will: mount the game's containers plus the mod's, load
/// each named package, and report every export that does not consume exactly its declared size.
/// That mismatch is what the engine's AsyncLoading2 turns into "ObjectSerializationError: Serial
/// size mismatch" and a crash on load, so catching it here keeps a broken mod from being shipped.
///
///   AtelierNative verify --paks D --aes HEX --usmap F --mod DIR --assets a;b;c [--out report.json]
/// </summary>
static class VerifyCommand
{
    sealed class Collector : ILogEventSink
    {
        public readonly List<string> Warnings = new();
        public void Emit(LogEvent e)
        {
            if (e.Level >= LogEventLevel.Warning)
                lock (Warnings) Warnings.Add(e.RenderMessage());
        }
    }

    public static int Run(string[] args)
    {
        try
        {
            var options = GameProvider.Options(args);
            var collector = new Collector();
            Log.Logger = new LoggerConfiguration().MinimumLevel.Warning().WriteTo.Sink(collector).CreateLogger();
            using var provider = GameProvider.Open(options["paks"], options["aes"], options.GetValueOrDefault("usmap"));
            foreach (var file in new DirectoryInfo(options["mod"]).EnumerateFiles("*", SearchOption.TopDirectoryOnly))
                if (file.Extension.Equals(".utoc", StringComparison.OrdinalIgnoreCase)
                    || file.Extension.Equals(".pak", StringComparison.OrdinalIgnoreCase) && !File.Exists(Path.ChangeExtension(file.FullName, ".utoc")))
                    provider.RegisterVfs(file);
            provider.Mount();
            var results = new List<object>();
            bool ok = true;
            foreach (var asset in options["assets"].Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
            {
                int before;
                lock (collector.Warnings) before = collector.Warnings.Count;
                string? error = null;
                var exports = new List<string>();
                try
                {
                    var package = provider.LoadPackage(asset);
                    foreach (var export in package.GetExports())
                        exports.Add($"{export.ExportType} {export.Name}");
                }
                catch (Exception e) { error = e.Message; }
                List<string> warnings;
                lock (collector.Warnings) warnings = collector.Warnings.Skip(before).ToList();
                var mismatches = warnings.Where(w => w.Contains("Did not read", StringComparison.Ordinal)).ToList();
                bool assetOk = error == null && mismatches.Count == 0;
                ok &= assetOk;
                results.Add(new { asset, ok = assetOk, error, mismatches, exports, warnings });
            }
            var report = JsonSerializer.Serialize(new { ok, results }, new JsonSerializerOptions { WriteIndented = true });
            if (options.TryGetValue("out", out var outPath)) File.WriteAllText(outPath, report);
            Console.WriteLine(report);
            return ok ? 0 : 3;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine("ERROR: " + error.Message);
            return 1;
        }
    }
}
