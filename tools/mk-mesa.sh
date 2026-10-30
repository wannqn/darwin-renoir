#!/bin/bash
# Build the Mesa26 OpenGL ES implementation behind userland/src/eagl.c and
# gl_osmesa.c with the kernel's cross compiler and the userland iOS16.5 SDK.
#
# The pinned upstream source is reconstructed by tools/mesa/prepare.py from
# tools/mesa/mesa26's consolidated donor patch and verified source manifest,
# then adapted for Renoir A642 (Gen6). Never apply the historical Mesa25
# tools/mesa/*.patch stack or overwrite this source with the old AIR/DRM trees.
# The donor's Gen8 paths remain generation-gated; this does not make A642 Gen8.
#
# DRIVERS defaults to softpipe,freedreno. RedwoodGPU supplies the MSM1.7
# softpin ABI through the bundled Darwin DRM bridge. OSMESA_SOFTWARE=1 keeps
# the existing explicit software-rendering path.
#
# Outputs in xnu-deps/build/mesa/out:
#   libOSMesa.8.dylib  install name /redwood/lib/libOSMesa.8.dylib
#   exported-gl.txt   exported gl* entry points for userland/mkeagl.py
#   gl.xml            matching Khronos registry
#   built-from        recipe/source/driver fingerprint, not a binary code hash
# AIR=1 also builds the optional donor air_run diagnostic, not a Metal runtime.
# Needs meson, ninja, bison, flex, python3 (3.12+ with venv), llvm-ar and the
# xnu-deps cross tools. Build layout is not promised to reproduce byte-for-byte.
set -eo pipefail
VERSION=26.2.5
ROOT=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
DRIVERS=${DRIVERS:-softpipe,freedreno}
# Keep userland's freshness check identical to the build's. This mode needs
# neither an SDK nor a configured xnu-deps environment.
fingerprint() {
	{ printf '%s\n' "$DRIVERS"; cat "$ROOT/tools/mk-mesa.sh" "$ROOT/tools/mesa/prepare.py" "$ROOT"/tools/mesa/mesa26/*; } | sha256sum
}
if [ "${1:-}" = --fingerprint ]; then
	fingerprint
	exit 0
fi
source "$ROOT/xnu-env.sh"
B=$ROOT/xnu-deps/build/mesa
SDK=$THEOS/sdks/iPhoneOS16.5.sdk
CC=$ROOT/xnu-deps/host/bin/xnu-clang
mkdir -p "$B/out"
cd "$B"

# Reconstruct from the archive when any preparation input changes; no patch
# is applied twice. Leave old Mesa25 source/builds untouched and unused.
PATCHES=$(cat "$ROOT/tools/mk-mesa.sh" "$ROOT/tools/mesa/prepare.py" "$ROOT"/tools/mesa/mesa26/* | sha256sum | cut -d' ' -f1)
if [ ! -d mesa-$VERSION ] || [ "$(cat mesa-$VERSION/.redwood-patches 2>/dev/null)" != "$PATCHES" ]; then
	[ -f mesa-$VERSION.tar.xz ] || curl -sL --fail -o mesa-$VERSION.tar.xz https://archive.mesa3d.org/mesa-$VERSION.tar.xz
	rm -rf mesa-$VERSION build-$VERSION-*
	rm -f out/air_run out/built-from
	python3 "$ROOT/tools/mesa/prepare.py" --archive "$B/mesa-$VERSION.tar.xz" --output "$B/mesa-$VERSION"
	echo "$PATCHES" > mesa-$VERSION/.redwood-patches
fi
if [ ! -x venv/bin/python3 ]; then
	python3 -m venv venv
	venv/bin/pip -q install mako pyyaml packaging
fi
export PATH=$B/venv/bin:$PATH

# the compiler is the kernel's wrapper: it names the target (arm64-apple-ios) and the linker (ld64)
cat > cross.ini <<INI
[binaries]
c = ['$CC', '-arch', 'arm64', '-isysroot', '$SDK']
cpp = ['$CC++', '-arch', 'arm64', '-isysroot', '$SDK', '-fuse-cxa-atexit']
objc = ['$CC', '-arch', 'arm64', '-isysroot', '$SDK']
ar = 'llvm-ar'
ranlib = 'llvm-ranlib'
strip = 'llvm-strip'
pkg-config = 'false'

[host_machine]
system = 'darwin'
subsystem = 'ios'
cpu_family = 'aarch64'
cpu = 'arm64'
endian = 'little'

[properties]
needs_exe_wrapper = true
INI
BUILD=build-$VERSION-${DRIVERS//,/-}
[ -f $BUILD/build.ninja ] || meson setup $BUILD mesa-$VERSION --cross-file cross.ini --wrap-mode=nofallback \
	--prefix=/redwood --libdir=lib --buildtype=release -Db_ndebug=true \
	-Dplatforms= -Dgallium-drivers="$DRIVERS" -Dfreedreno-kmds=msm -Dvulkan-drivers= -Dglx=disabled -Degl=disabled -Dgbm=disabled \
	-Dosmesa=true -Dllvm=disabled -Dshared-glapi=enabled -Dgles1=disabled -Dgles2=enabled -Dopengl=true \
	-Dzstd=disabled -Dxmlconfig=disabled -Dexpat=disabled -Dshader-cache=disabled -Dvalgrind=disabled \
	-Dlibunwind=disabled -Dglvnd=disabled -Dvideo-codecs= -Dtools= -Dgallium-va=disabled \
	-Dlmsensors=disabled -Dbuild-tests=false > meson-setup.log
ninja -C $BUILD src/gallium/targets/osmesa/libOSMesa.8.dylib > ninja.log
# air_run draws with a translated Metal shader and reads the pixels back; it is
# the only way to find out whether the Adreno takes work that did not come from
# the window server. Built only when asked, since it is a test program.
if [ "${AIR:-}" = 1 ]; then
	ninja -C $BUILD src/gallium/drivers/freedreno/air_run >> ninja.log
	cp $BUILD/src/gallium/drivers/freedreno/air_run out/air_run
	echo "mk-mesa.sh: $B/out/air_run ($(stat -c %s out/air_run) bytes)"
fi

llvm-strip -x -o out/libOSMesa.8.dylib $BUILD/src/gallium/targets/osmesa/libOSMesa.8.dylib
install_name_tool -id /redwood/lib/libOSMesa.8.dylib out/libOSMesa.8.dylib
nm -gU out/libOSMesa.8.dylib | awk '$3 ~ /^_gl/ { print substr($3, 2) }' > out/exported-gl.txt
cp mesa-$VERSION/src/mesa/glapi/glapi/registry/gl.xml out/gl.xml
# userland/build.sh asks this script for the same fingerprint.
fingerprint > out/built-from
echo "mk-mesa.sh: Mesa $VERSION ($DRIVERS): $B/out/libOSMesa.8.dylib, $(stat -c %s out/libOSMesa.8.dylib) bytes," \
	"$(wc -l < out/exported-gl.txt) gl* functions"
