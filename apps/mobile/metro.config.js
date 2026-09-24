const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');
const config = getDefaultConfig(__dirname);
// This app has its own lockfile; only the shared, dependency-free API source is watched.
config.watchFolders = [path.resolve(__dirname, '../../packages')];
config.resolver.nodeModulesPaths = [path.resolve(__dirname, 'node_modules')];
module.exports = config;
