project(
  'vertexwrite',
  version: '0.7.3',
  meson_version: '>=0.59.0',
)

app_id = 'com.canarybuilds.VertexWrite'
app_name = 'vertexwrite'
app_install_dir = join_paths(get_option('prefix'), get_option('libdir'), app_name)

install_data(
  [
    'vertexwrite.py',
    'vertexwrite_core.py',
    'vertexwrite_files.py',
    'style.css',
    'CHANGELOG.md',
    'icon.png',
  ],
  install_dir: join_paths(get_option('libdir'), app_name),
)

launcher_conf = configuration_data()
launcher_conf.set('APP_INSTALL_DIR', app_install_dir)

configure_file(
  input: 'data/vertexwrite.in',
  output: app_name,
  configuration: launcher_conf,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

install_data(
  'data/com.canarybuilds.VertexWrite.desktop',
  install_dir: join_paths(get_option('datadir'), 'applications'),
)

install_data(
  'data/com.canarybuilds.VertexWrite.metainfo.xml',
  install_dir: join_paths(get_option('datadir'), 'metainfo'),
)

foreach size : ['16', '32', '48', '64', '128', '256']
  install_data(
    'icon-' + size + '.png',
    rename: app_id + '.png',
    install_dir: join_paths(
      get_option('datadir'),
      'icons',
      'hicolor',
      size + 'x' + size,
      'apps',
    ),
  )
endforeach

install_data(
  'icon.png',
  rename: app_id + '.png',
  install_dir: join_paths(
    get_option('datadir'),
    'icons',
    'hicolor',
    '512x512',
    'apps',
  ),
)
