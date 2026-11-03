#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK="$HOME/lib/android-sdk"
if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then SDK="$ANDROID_SDK_ROOT"; elif [[ -n "${ANDROID_HOME:-}" ]]; then SDK="$ANDROID_HOME"; fi
OUT_DIR="$HOME/storage/downloads"
DEST="$OUT_DIR/ProductionMobile-debug.apk"
fail() { echo "ERROR: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

command -v java >/dev/null 2>&1 || fail "Java 17+ is required."
[[ -d "$SDK/platforms/android-35" ]] || fail "Android SDK platform 35 missing: $SDK"
[[ -d "$SDK/build-tools" ]] || fail "Android SDK build-tools missing."
[[ -d "$OUT_DIR" ]] || fail "Shared Downloads unavailable. Run termux-setup-storage."
if [[ -x "$SCRIPT_DIR/gradlew" ]]; then
  GRADLE=("$SCRIPT_DIR/gradlew")
elif command -v gradle >/dev/null 2>&1; then
  GRADLE=(gradle)
else
  fail "Gradle 8.9+ not found. Install Gradle or add the Gradle wrapper."
fi

export ANDROID_HOME="$SDK"
export ANDROID_SDK_ROOT="$SDK"
step "Build Production Mobile debug APK"
"${GRADLE[@]}" -p "$SCRIPT_DIR" --no-daemon assembleDebug

APK="$SCRIPT_DIR/app/build/outputs/apk/debug/app-debug.apk"
[[ -s "$APK" ]] || fail "Gradle did not produce the expected APK."
TMP="$OUT_DIR/.ProductionMobile-debug.apk.tmp"
cp "$APK" "$TMP"

ZIPALIGN="$(find "$SDK/build-tools" -type f -name zipalign | sort -V | tail -n 1)"
APKSIGNER="$(find "$SDK/build-tools" -type f -name apksigner | sort -V | tail -n 1)"
[[ -x "$ZIPALIGN" ]] || fail "zipalign not found in SDK build-tools."
[[ -x "$APKSIGNER" ]] || fail "apksigner not found in SDK build-tools."
"$ZIPALIGN" -c -v 4 "$TMP" >/dev/null || { rm -f "$TMP"; fail "APK alignment verification failed."; }
"$APKSIGNER" verify "$TMP" >/dev/null || { rm -f "$TMP"; fail "APK signature verification failed."; }

mv -f "$TMP" "$DEST"
echo
echo "Build completed successfully."
echo "APK: $DEST"
ls -lh "$DEST"
echo "Development build only. Release signing will be configured before pilot distribution."
