#!/bin/bash

rm -rf dist

pyinstaller --clean --windowed --icon python.icns --target-arch arm64 cleaner.py

rm *.spec
rm -rf build
rm -rf dist/cleaner
