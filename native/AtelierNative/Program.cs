using Atelier.Native;

// One executable, four jobs. Each subcommand keeps the exact argument contract of the separate
// tool it replaces (AtelierMesh, AtelierAnimation, AtelierImport, AtelierMorphCheck), so callers
// only change the executable path and prepend the subcommand.
if (args.Length == 0 || args[0] is "-h" or "--help" or "help")
{
    Console.WriteLine("""
        AtelierNative <command> [options]

          mesh         --paks D --aes HEX [--usmap F] --asset PATH --out DIR [--lods first|all] [--morphs 1|0]
          animation    --paks D --aes HEX --usmap F --mesh PATH --animation PATH --out FILE
          serve        persistent import server (JSON lines on stdin/stdout)
          morph-check  <buffer.bin> <out.json>
          verify       --paks D --aes HEX --usmap F --mod DIR --assets a;b;c [--out report.json]
          version
        """);
    return args.Length == 0 ? 2 : 0;
}
return args[0] switch
{
    "mesh" => MeshCommand.Run(args[1..]),
    "animation" => AnimationCommand.Run(args[1..]),
    "serve" => ImportServer.Run(),
    "morph-check" => MorphCheckCommand.Run(args[1..]),
    "verify" => VerifyCommand.Run(args[1..]),
    "version" or "--version" => Version(),
    _ => Unknown(args[0]),
};

static int Version()
{
    var cue = typeof(CUE4Parse.FileProvider.DefaultFileProvider).Assembly.GetName().Version;
    Console.WriteLine($"AtelierNative {typeof(GameProvider).Assembly.GetName().Version} (CUE4Parse {cue}; natives {(GameProvider.NativesAvailable() ? "ok" : "missing")})");
    return 0;
}

static int Unknown(string command)
{
    Console.Error.WriteLine($"Unknown command: {command}. Run 'AtelierNative help'.");
    return 2;
}
