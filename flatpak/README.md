# Flatpak packaging

## Build for validation (without installing the app)

```bash
sudo apt install flatpak flatpak-builder
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user flathub org.gnome.Sdk//50 org.gnome.Platform//50 org.flatpak.Builder
cd /path/to/vertexwrite
flatpak run --command=flathub-build org.flatpak.Builder flatpak/com.canarybuilds.VertexWrite.yml
```

Required policy checks before submitting or updating the PR:

```bash
flatpak run --command=flatpak-builder-lint org.flatpak.Builder manifest flatpak/com.canarybuilds.VertexWrite.yml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder appstream data/com.canarybuilds.VertexWrite.metainfo.xml
flatpak run --command=flatpak-builder-lint org.flatpak.Builder builddir builddir
flatpak run --command=flatpak-builder-lint org.flatpak.Builder repo repo
```

`gtksourceview4` is built in the Flatpak because VertexWrite is a GTK 3 app and
GtkSourceView 5 loads GTK 4.

## Regenerate Python dependencies

Python dependencies are generated with `flatpak-builder-tools` instead of
maintaining wheel URLs by hand:

```bash
flatpak-pip-generator \
  --runtime=org.gnome.Sdk//50 \
  --requirements-file=flatpak/requirements.txt \
  --ignore-installed=markdown,pygments \
  --prefer-wheels=bcrypt,cryptography,cffi,pynacl \
  --wheel-arches=x86_64,aarch64 \
  --output=flatpak/python3-requirements
```

`markdown` and `pygments` are ignored from the SDK so the Flatpak bundles the
pinned versions used by VertexWrite. The compiled Paramiko dependencies use
generator-managed wheels for both Flathub architectures.

## Create a distributable bundle (optional)

```bash
flatpak build-bundle repo com.canarybuilds.VertexWrite.flatpak com.canarybuilds.VertexWrite
```

## Submit to Flathub (manual maintainer action)

Flathub does not accept direct binary uploads. You submit a pull request to the
`flathub/flathub` GitHub repository.

Flathub policy requires new app submissions to be prepared, opened, and reviewed
by a human maintainer. Do not use AI agents or automated tools to open or drive
the submission PR.

```bash
git clone https://github.com/flathub/flathub.git
cd flathub
git checkout --track origin/new-pr
git checkout -b add-com.canarybuilds.VertexWrite
cp /path/to/vertexwrite/flatpak/com.canarybuilds.VertexWrite.yml .
git add com.canarybuilds.VertexWrite.yml
git commit -m "Add com.canarybuilds.VertexWrite"
git push origin add-com.canarybuilds.VertexWrite
```

Then open a PR from your fork branch to `flathub/flathub` with base `new-pr`.
After review/merge, Flathub builds and publishes automatically.

Before opening the PR, ensure screenshot URLs in
`com.canarybuilds.VertexWrite.metainfo.xml` point to a stable commit/tag URL and
not a moving branch.
