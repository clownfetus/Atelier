"""List a legacy (non-IoStore) .pak's files before anything extracts it.

Mods that are only a .pak carry loose files the game reads directly: config overrides, Wwise sound
banks, older cooked assets. Atelier's hardened container tool reads IoStore only, and the upstream
one that reads paks writes whatever paths an archive names. So the pak's own index is read here
first (UE5 pak versions 8 to 11, with an optionally encrypted index), every name is checked, and
extraction runs only when each file would land inside the output folder.

A pak whose directory index was removed lists no file names; it is reported as such, never guessed.
"""
import os
import struct

import io_lib

MAGIC = 0x5A6F12E1
_NAMES = 5                       # compression method names in a v8+ footer
_FOOTER = 16 + 1 + 4 + 4 + 8 + 8 + 20 + _NAMES * 32


class PakError(ValueError):
    pass


class _Reader:
    def __init__(self, data):
        self.data, self.at = data, 0

    def take(self, n):
        if n < 0 or self.at + n > len(self.data):
            raise PakError('The pak index is truncated.')
        chunk = self.data[self.at:self.at + n]
        self.at += n
        return chunk

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def i32(self):
        return struct.unpack('<i', self.take(4))[0]

    def fstring(self):
        n = self.i32()
        if n == 0:
            return ''
        if abs(n) > 4096:
            raise PakError('The pak index has an unreadable name.')
        if n > 0:
            return self.take(n).rstrip(b'\0').decode('latin-1')
        return self.take(-n * 2).decode('utf-16-le').rstrip('\0')


def _align(n):
    return (n + 15) & ~15


def _swap(data):
    """Reverse the bytes of each 4-byte word."""
    return b''.join(data[i:i + 4][::-1] for i in range(0, len(data), 4))


# Paks built for Marvel Rivals encrypt their index with the game key in the word-swapped form: the
# key and the data both have each 4-byte word reversed around AES. IoStore containers use plain AES.
# The index says which applies: its mount point decrypts to readable text only under the right one.
_CIPHERS = {
    'plain': lambda data: io_lib.aes_decrypt(data),
    'swapped': lambda data: _swap(io_lib.aes_decrypt(_swap(data), _swap(io_lib.AES_KEY))),
}


def _mount_reads(index):
    try:
        n = struct.unpack_from('<i', index)[0]
        return 0 < n <= 1024 and index[3 + n:4 + n] == b'\0' and index[4:3 + n].decode('ascii').isprintable()
    except (struct.error, UnicodeDecodeError):
        return False


class Pak:
    """A pak's mount point, its file count and the names its directory index gives."""

    def __init__(self, path):
        self.path = path
        self.size = os.path.getsize(path)
        with open(path, 'rb') as stream:
            stream.seek(max(0, self.size - _FOOTER - 64))
            tail = stream.read()
        at = tail.rfind(struct.pack('<I', MAGIC))
        if at < 17:
            raise PakError('This is not a pak file Atelier can read.')
        self.encrypted_index = tail[at - 1] != 0
        self.version, offset, size = struct.unpack_from('<iqq', tail, at + 4)
        if not 8 <= self.version <= 11:
            raise PakError('This pak uses version %d, which Atelier cannot read.' % self.version)
        self.cipher = 'plain'
        data = self._block(offset, size)
        if self.encrypted_index and not _mount_reads(data):
            self.cipher = 'swapped'
            data = self._block(offset, size)
            if not _mount_reads(data):
                raise PakError('This pak is encrypted with a key Atelier does not have.')
        index = _Reader(data)
        self.mount = index.fstring()
        self.count = index.i32()
        index.take(8)                                  # path hash seed
        if index.u32():                                # path hash index: hashes, not names
            index.take(8 + 8 + 20)
        self.names = []
        if index.u32():
            dir_offset, dir_size = struct.unpack('<qq', index.take(16))
            names = _Reader(self._block(dir_offset, dir_size))
            for _ in range(names.i32()):
                folder = names.fstring()
                for _ in range(names.i32()):
                    self.names.append((folder + names.fstring()).lstrip('/'))
                    names.i32()                        # where the entry is described

    def _block(self, offset, size):
        if not (0 < size <= self.size and 0 <= offset <= self.size - size):
            raise PakError('The pak index is outside the file.')
        with open(self.path, 'rb') as stream:
            stream.seek(offset)
            data = stream.read(_align(size) if self.encrypted_index else size)
        if self.encrypted_index:
            data = _CIPHERS[self.cipher](data)
        return data[:size]


def safe_parts(name):
    """The path's folders and file name, or None when it could leave the output folder."""
    parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.')]
    if not parts or any(p == '..' or ':' in p or any(ord(c) < 32 for c in p) for p in parts):
        return None
    return parts


def check(path):
    """(names, problem). names are the files extraction may write; problem explains why not."""
    pak = Pak(path)
    mount = pak.mount.replace('\\', '/')
    if any(p not in ('..', '.', '') for p in mount.split('/')):
        return [], 'This pak mounts its files at %s, which Atelier does not extract.' % pak.mount
    unsafe = [n for n in pak.names if safe_parts(n) is None]
    if unsafe:
        return [], 'This pak names a file outside its own folders (%s), so Atelier did not extract it.' % unsafe[0]
    if pak.count and not pak.names:
        return [], 'This pak lists %d files but no file names. Its author may have protected it.' % pak.count
    return pak.names, None
