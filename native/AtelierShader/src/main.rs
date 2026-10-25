use anyhow::{bail, Context, Result};
use clap::{Args, Parser, Subcommand};
use retoc::shader_library::{atelier_extract, atelier_index, atelier_libraries, atelier_patch};
use retoc::{ActionToLegacyBatch, ActionToLegacyBatchItem, ActionToZen, Config, EngineVersion, FGuid};
use std::fs::{self, File};
use std::io::{BufWriter, Write};
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(Parser)]
#[command(name = "retoc-rivals-cli", version = "3.10.2-atelier.1",
    about = "Atelier shader fork of Rivals retoc (source build)")]
struct Cli {
    /// Container read key. Atelier supplies ATELIER_RETOC_AES_KEY privately.
    #[arg(short, long, global = true)]
    aes_key: Option<String>,
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Read shader metadata without decompressing the shader groups.
    DumpShaders(Dump),
    /// Extract one shader, including its Unreal wrapper.
    ExtractShader(Extract),
    /// Rebuild a complete loose library with one replacement shader.
    PatchShader(Patch),
    /// Pack loose Unreal packages and shader libraries into an IoStore triple.
    Pack(Pack),
    /// Extract selected Unreal packages, with optional game dependencies.
    Unpack(Unpack),
    /// Print container information.
    Info { input: PathBuf },
}

#[derive(Args)]
struct Inputs {
    #[arg(required = true, num_args = 1..)]
    input: Vec<PathBuf>,
}

#[derive(Args)]
struct Dump {
    #[command(flatten)]
    inputs: Inputs,
    #[arg(short, long)]
    output: PathBuf,
    /// Indexing is metadata-only. Full bulk dumps are intentionally unsupported.
    #[arg(long, required = true)]
    index_only: bool,
}

#[derive(Args)]
struct Extract {
    #[command(flatten)]
    inputs: Inputs,
    #[arg(short, long)]
    library: String,
    #[arg(short = 's', long)]
    shader: usize,
    #[arg(short, long)]
    output: PathBuf,
}

#[derive(Args)]
struct Patch {
    #[command(flatten)]
    extract: Extract,
    #[arg(short, long)]
    blob: PathBuf,
}

#[derive(Args)]
struct Pack {
    input: PathBuf,
    #[arg(short, long)]
    output: PathBuf,
    /// Accepted for the app's package interface; loose inputs are self-contained.
    #[arg(long)]
    game_paks_dir: Option<PathBuf>,
}

#[derive(Args)]
struct Unpack {
    input: PathBuf,
    #[arg(short, long)]
    output: PathBuf,
    #[arg(short, long)]
    filter: Vec<String>,
    #[arg(long)]
    game_paks_dir: Option<PathBuf>,
}

fn config(key: Option<String>) -> Result<Arc<Config>> {
    let mut config = Config::default();
    if let Some(key) = key.or_else(|| std::env::var("ATELIER_RETOC_AES_KEY").ok()) {
        // Never let an invalid credential reach clap's value-in-error formatting.
        let key = key.parse().map_err(|_| anyhow::anyhow!("Invalid container read key"))?;
        config.aes_keys.insert(FGuid::default(), key);
    }
    // Read credentials do not turn on IoStore output encryption.
    Ok(Arc::new(config))
}

fn open(inputs: &Inputs, config: Arc<Config>) -> Result<Box<dyn retoc::IoStoreTrait>> {
    for input in &inputs.input {
        if !input.is_file() || input.extension().is_none_or(|ext| ext != "utoc") {
            bail!("Each input must be an existing .utoc file");
        }
    }
    retoc::open_iostore_paths(&inputs.input, config)
}

fn fresh_directory(output: &Path, action: impl FnOnce(&Path) -> Result<()>) -> Result<()> {
    if output.symlink_metadata().is_ok_and(|m| m.file_type().is_symlink()) {
        bail!("Output directory cannot be a symbolic link");
    }
    if output.exists() && (!output.is_dir() || fs::read_dir(output)?.next().is_some()) {
        bail!("Output must be a new or empty directory");
    }
    let parent = output.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(parent)?;
    let temporary = tempfile::Builder::new().prefix(".atelier-retoc-").tempdir_in(parent)?;
    action(temporary.path())?;
    if output.exists() {
        fs::remove_dir(output)?;
    }
    fs::rename(temporary.path(), output)?;
    Ok(())
}

fn write_new(output: &Path, bytes: &[u8]) -> Result<()> {
    let parent = output.parent().filter(|p| !p.as_os_str().is_empty()).unwrap_or(Path::new("."));
    fs::create_dir_all(parent)?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    temporary.write_all(bytes)?;
    temporary.as_file().sync_all()?;
    temporary.persist_noclobber(output).map_err(|_| anyhow::anyhow!("Output already exists or cannot be published"))?;
    Ok(())
}

fn run(cli: Cli) -> Result<()> {
    let key = cli.aes_key.or_else(|| std::env::var("ATELIER_RETOC_AES_KEY").ok());
    let config = config(key.clone())?;
    match cli.command {
        Command::DumpShaders(args) => {
            let store = open(&args.inputs, config)?;
            let libraries = atelier_libraries(&*store)?;
            if libraries.is_empty() { bail!("No shader libraries found in the selected containers"); }
            fresh_directory(&args.output, |stage| {
                for (name, id) in libraries {
                    let folder = stage.join(&name);
                    fs::create_dir(&folder)?;
                    let mut output = BufWriter::new(File::create(folder.join("index.json"))?);
                    let count = atelier_index(&*store, id, &name, &mut output)?;
                    output.flush()?;
                    println!("Indexed {name}: {count} shaders");
                }
                Ok(())
            })
        }
        Command::ExtractShader(args) => {
            let store = open(&args.inputs, config)?;
            let bytes = atelier_extract(&*store, &args.library, args.shader)?;
            write_new(&args.output, &bytes)
        }
        Command::PatchShader(args) => {
            let store = open(&args.extract.inputs, config)?;
            if fs::metadata(&args.blob)?.len() > 64 * 1024 * 1024 { bail!("Replacement shader is too large"); }
            let bytes = fs::read(&args.blob)?;
            fresh_directory(&args.extract.output, |stage| {
                atelier_patch(&*store, &args.extract.library, args.extract.shader, &bytes, stage)
            })
        }
        Command::Pack(args) => {
            if !args.input.is_dir() { bail!("Pack input must be a loose asset directory"); }
            let pak_key: repak::utils::AesKey = key.context("Pack requires the configured game key for its companion pak index")?
                .parse().map_err(|_| anyhow::anyhow!("Invalid companion pak key"))?;
            let name = args.input.file_name().and_then(|s| s.to_str()).context("Invalid pack input name")?;
            let name = if name.ends_with("_9999999_P") { name.to_string() } else { format!("{name}_9999999_P") };
            fresh_directory(&args.output, |stage| {
                retoc::action_to_zen(ActionToZen::new(args.input.clone(), stage.join(format!("{name}.utoc")),
                    EngineVersion::UE5_3, Some(retoc::compression::CompressionMethod::Oodle)), config)?;
                let writer = BufWriter::new(File::create(stage.join(format!("{name}.pak")))?);
                repak::PakBuilder::new().key(pak_key.0).writer(writer, repak::Version::V11, "../../../".into(), Some(0)).write_index()?;
                Ok(())
            })
        }
        Command::Unpack(args) => {
            let selected = args.input.canonicalize()?;
            let mut inputs = vec![selected.clone()];
            if let Some(game) = args.game_paks_dir {
                let mut paths = fs::read_dir(game)?.map(|p| p.map(|p| p.path())).collect::<std::io::Result<Vec<_>>>()?;
                paths.sort();
                for path in paths {
                    let name = path.file_stem().and_then(|s| s.to_str()).unwrap_or("").to_ascii_lowercase();
                    if path.extension().is_some_and(|s| s == "utoc") &&
                        (name == "global" || (name.starts_with("pakchunk") && name.contains("character"))) {
                        let path = path.canonicalize()?;
                        if !inputs.contains(&path) { inputs.push(path); }
                    }
                }
            }
            retoc::action_to_legacy_batch(ActionToLegacyBatch {
                inputs, items: vec![ActionToLegacyBatchItem { inputs: vec![selected], output: args.output, filter: args.filter }],
                no_assets: false, no_shaders: true, no_compres_shaders: true, dry_run: false,
                version: None, verbose: false, debug: false, no_parallel: false,
            }, config)
        }
        Command::Info { input } => {
            if input.extension().is_some_and(|ext| ext == "pak") {
                let mut builder = repak::PakBuilder::new();
                if let Some(key) = key {
                    let key: repak::utils::AesKey = key.parse().map_err(|_| anyhow::anyhow!("Invalid companion pak key"))?;
                    builder = builder.key(key.0);
                }
                let pak = builder.reader(&mut File::open(input)?)?;
                println!("{}", serde_json::json!({"encrypted_index": pak.encrypted_index(), "files": pak.files().len()}));
                return Ok(());
            }
            retoc::open_iostore(input, config)?.print_info(0);
            Ok(())
        }
    }
}

fn main() {
    if let Err(error) = run(Cli::parse()) {
        eprintln!("{error:#}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_app_command_interfaces_and_rejects_bad_indices() {
        for args in [
            vec!["tool", "dump-shaders", "a.utoc", "global.utoc", "-o", "index", "--index-only"],
            vec!["tool", "extract-shader", "a.utoc", "global.utoc", "-l", "Global", "-s", "20", "-o", "blob"],
            vec!["tool", "patch-shader", "a.utoc", "-l", "Global", "-s", "20", "-b", "blob", "-o", "stage"],
            vec!["tool", "-a", "test-read-key", "unpack", "a.utoc", "--filter", "one", "--filter", "two", "--game-paks-dir", "paks", "-o", "work"],
            vec!["tool", "pack", "stage", "--game-paks-dir", "paks", "-o", "mod"],
        ] { assert!(Cli::try_parse_from(args).is_ok()); }
        assert!(Cli::try_parse_from(["tool", "extract-shader", "a.utoc", "-l", "Global", "-s", "-1", "-o", "blob"]).is_err());
    }

    #[test]
    fn failed_rebuild_publishes_nothing_and_preserves_existing_data() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("out");
        assert!(fresh_directory(&output, |stage| {
            fs::write(stage.join("partial"), b"incomplete")?;
            bail!("fixture failure")
        }).is_err());
        assert!(!output.exists());
        fs::create_dir(&output).unwrap();
        fs::write(output.join("user-file"), b"preserve").unwrap();
        assert!(fresh_directory(&output, |_| Ok(())).is_err());
        assert_eq!(fs::read(output.join("user-file")).unwrap(), b"preserve");
    }

    #[test]
    fn extracting_does_not_overwrite_an_existing_file() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("shader.bin");
        write_new(&output, b"original").unwrap();
        assert!(write_new(&output, b"replacement").is_err());
        assert_eq!(fs::read(output).unwrap(), b"original");
    }
}
