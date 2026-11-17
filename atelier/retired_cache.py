"""Remove cache folders that earlier versions of Atelier wrote and nothing reads any more."""
import os
import threading


def remove_vanilla_paks(cache_root):
    """Delete the vanilla_paks mirror that Atelier kept under _cache from 0.3.3 until 1.1.3.

    It held hard links to the game's top-level Paks files, so 3D previews never saw installed mods.
    1.1.3 stopped using it but left it in place, and once the game patches, Steam replaces its files
    and the mirror's links become the only names for the previous season's files: about 80 GB that
    nothing reads. Removing a hard link never touches the game's own copy.

    Only plain files directly inside the folder go, since that is all the mirror ever held. A
    subfolder, a link or a junction is left alone (with the folder around it), and so is the folder
    when it is itself a link. A file that cannot be removed now, for example because it is open, is
    tried again at the next start. Returns how many files were removed."""
    folder = os.path.join(cache_root, "vanilla_paks")
    if os.path.islink(folder) or os.path.isjunction(folder) or not os.path.isdir(folder):
        return 0
    removed = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        os.remove(entry.path)
                        removed += 1
                except OSError:
                    pass
    except OSError:
        return removed
    try:
        os.rmdir(folder)
    except OSError:
        pass
    return removed


def start(cache_root):
    """Clean up in the background, so a slow disk never holds up the window opening."""
    def run():
        removed = remove_vanilla_paks(cache_root)
        if removed:
            print(f"[cleanup] removed {removed} files of the retired vanilla_paks mirror", flush=True)
    threading.Thread(target=run, name="retired-cache", daemon=True).start()
