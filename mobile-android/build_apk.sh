#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SDK="$HOME/lib/android-sdk"
if [[ -n "${ANDROID_SDK_ROOT:-}" ]]; then
  SDK="$ANDROID_SDK_ROOT"
elif [[ -n "${ANDROID_HOME:-}" ]]; then
  SDK="$ANDROID_HOME"
fi

OUT_DIR="$HOME/storage/downloads"
DEST="$OUT_DIR/ProductionMobile-debug.apk"
SIGNING_DIR="$HOME/.android"
KEYSTORE="$SIGNING_DIR/production-mobile.jks"
KEY_ALIAS="productionmobile"

fail() { echo "ERROR: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

command -v java >/dev/null 2>&1 || fail "Java 17+ is required."
command -v keytool >/dev/null 2>&1 || fail "keytool is required (install a Java 17+ JDK)."
command -v python >/dev/null 2>&1 || fail "Python is required for APK ZIP integrity checks."
[[ -d "$SDK/platforms/android-34" ]] || fail "Android SDK platform 34 missing: $SDK. Install with sdkmanager \"platforms;android-34\"."
[[ -d "$SDK/build-tools" ]] || fail "Android SDK build-tools missing."
[[ -d "$OUT_DIR" ]] || fail "Shared Downloads unavailable. Run termux-setup-storage."

if [[ -x "$SCRIPT_DIR/gradlew" ]]; then
  GRADLE=("$SCRIPT_DIR/gradlew")
elif command -v gradle >/dev/null 2>&1; then
  GRADLE=(gradle)
else
  fail "Gradle 8.9+ not found. Install Gradle or add the Gradle wrapper."
fi

# Use Termux's native ARM64 zipalign from PATH. The SDK copy may be x86_64.
ZIPALIGN="$(command -v zipalign || true)"
[[ -n "$ZIPALIGN" && -x "$ZIPALIGN" ]] || fail "Native zipalign not found. Install the Termux package that provides zipalign (commonly: pkg install aapt)."

APKSIGNER="$(command -v apksigner || true)"
if [[ -z "$APKSIGNER" ]]; then
  APKSIGNER="$(find "$SDK/build-tools" -type f -name apksigner | sort -V | tail -n 1)"
fi
[[ -n "$APKSIGNER" && -x "$APKSIGNER" ]] || fail "apksigner not found in PATH or SDK build-tools."

# Create a separate, persistent signing identity for Production Mobile.
# Never reuse the MobileOperationsController keystore and never store passwords in Git.
mkdir -p "$SIGNING_DIR"
chmod 700 "$SIGNING_DIR"
if [[ ! -f "$KEYSTORE" ]]; then
  step "Create the Production Mobile signing keystore"
  echo "A new dedicated keystore will be created at: $KEYSTORE"
  echo "Choose a strong password and keep a secure backup. The password is not saved by this script."
  keytool -genkeypair -v \
    -keystore "$KEYSTORE" \
    -alias "$KEY_ALIAS" \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=Production Mobile, OU=Android, O=ProductionReviewWebApp, C=IN"
  [[ -s "$KEYSTORE" ]] || fail "Keystore creation did not produce $KEYSTORE."
  chmod 600 "$KEYSTORE"
else
  step "Use existing Production Mobile signing keystore"
  echo "$KEYSTORE"
fi

export ANDROID_HOME="$SDK"
export ANDROID_SDK_ROOT="$SDK"

step "Build Production Mobile debug APK"
"${GRADLE[@]}" -p "$SCRIPT_DIR" --no-daemon assembleDebug

APK="$SCRIPT_DIR/app/build/outputs/apk/debug/app-debug.apk"
[[ -s "$APK" ]] || fail "Gradle did not produce the expected APK."

WORK_DIR="$(mktemp -d "$OUT_DIR/.production-mobile-sign.XXXXXX")"
cleanup() { rm -rf "$WORK_DIR"; }
trap cleanup EXIT
ALIGNED="$WORK_DIR/ProductionMobile-debug-aligned.apk"
SIGNED="$WORK_DIR/ProductionMobile-debug-signed.apk"

step "Align APK"
"$ZIPALIGN" -f -p 4 "$APK" "$ALIGNED"
"$ZIPALIGN" -c -v 4 "$ALIGNED" >/dev/null || fail "APK alignment verification failed."

step "Check APK archive integrity before signing"
python - "$ALIGNED" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as apk:
    bad = apk.testzip()
    if bad:
        raise SystemExit(f"APK ZIP integrity check failed at: {bad}")
print("APK ZIP integrity: OK")
PY

step "Sign APK with the dedicated Production Mobile key"
echo "Enter the keystore password when apksigner prompts. Passwords are not stored."
"$APKSIGNER" sign \
  --ks "$KEYSTORE" \
  --ks-key-alias "$KEY_ALIAS" \
  --out "$SIGNED" \
  "$ALIGNED"

step "Verify signed APK"
"$APKSIGNER" verify --verbose "$SIGNED" || fail "APK signature verification failed."
python - "$SIGNED" <<'PY'
import sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as apk:
    bad = apk.testzip()
    if bad:
        raise SystemExit(f"Signed APK ZIP integrity check failed at: {bad}")
print("Signed APK ZIP integrity: OK")
PY

mv -f "$SIGNED" "$DEST"
echo
echo "Build and signing completed successfully."
echo "APK: $DEST"
ls -lh "$DEST"
echo "Signing keystore: $KEYSTORE"
echo "Alias: $KEY_ALIAS"
echo "Development/debug application build. Keep the keystore and its password safe; future updates must use the same key."
