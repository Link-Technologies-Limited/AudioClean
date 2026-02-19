# audioclean

npm wrapper for the AudioClean CLI using precompiled binaries.

## Install

```bash
npm install -g @linktechnologies/audioclean
```

Or install it in your project:

```bash
npm install @linktechnologies/audioclean
```

## Usage

```bash
audioclean --help
```

All CLI args are passed through directly to the platform binary.

## Binary Layout

Binaries are expected in `bin/` with these names:

- `audioclean-linux-x64`
- `audioclean-linux-arm64`
- `audioclean-darwin-x64`
- `audioclean-darwin-arm64`

This package currently includes:

- `audioclean-linux-x64`

If you want macOS and additional Linux architecture support, place the corresponding compiled binaries in `bin/` before publishing.

## Publish

```bash
cd packaging/npm
npm publish --access public
```
