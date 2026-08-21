from __future__ import annotations

BEHAVIORS = {
    "integrity_check": {
        "label": "Kiem tra tinh toan ven",
        "description": "Ung dung kiem tra mot thuoc tinh cua APK, DEX, chu ky hoac moi truong thuc thi.",
        "suggestions": [
            "Hook/Patch tra ve hang so chu ky chuan tai PackageManager.getPackageInfo()",
            "Sua lệnh nhay re nhanh dieu kien (if-eqz -> goto / nop) sau ham verifySignature",
        ],
    },
    "debug_detection": {
        "label": "Phat hien go lỗi",
        "description": "Ung dung kiem tra debugger hoac trang thai debug.",
        "suggestions": [
            "Sua tra ve `const/4 v0, 0x0` tai phuong thuc goi Debug.isDebuggerConnected()",
            "Nop (xoa) lệnh re nhanh if-nez kiem tra co debug",
        ],
    },
    "pro_premium_check": {
        "label": "Kiem tra Pro / Premium",
        "description": "Ung dung kiem tra trang thai tai khoan Pro, VIP, Premium hoac kiem tra tinh nang tra phi.",
        "suggestions": [
            "Patch cac phuong thuc getter `isPro()`, `isPremium()`, `isVip()` tra ve true (`const/4 v0, 0x1`)",
            "Nop lệnh re nhanh dieu kien (if-eqz / if-nez) nam ngay sau lệnh goi API kiem tra ban quyen",
        ],
    },
    "login_authentication": {
        "label": "Xac thuc dang nhap / phien dang nhap",
        "description": "Ung dung co luong dang nhap, xac thuc tai khoan, token hoac kiem tra trang thai da dang nhap.",
        "suggestions": [
            "Patch getter `isLoggedIn()`, `isAuthenticated()`, `hasSession()` tra ve true",
            "Patch ham `login()`/`authenticate()` tra ve dang nhap thanh cong",
            "Vo hieu hoa dieu kien bat buoc dang nhap de khong mo man hinh Login",
            "Hook `FirebaseAuth.getCurrentUser()`/`signInWithEmailAndPassword()` de gia lap tai khoan da dang nhap",
        ],
    },
    "google_billing": {
        "label": "Thanh toan Google Play Billing",
        "description": "Ung dung tich hop thu vien Google Play In-App Billing (com.android.billingclient).",
        "suggestions": [
            "Override callback BillingClient / `onPurchasesUpđạted()` luon tra ve BillingResponseCode.OK (0x0)",
            "Patch `getPurchaseState()` tra ve `0` (PURCHASED)",
            "Hook `queryPurchasesAsync()` de gia lap danh sach Purchase hop le",
        ],
    },
    "ssl_pinning": {
        "label": "Kiem tra SSL Certificate / Pinning",
        "description": "Ung dung cau hinh TrustManager, HostnameVerifier hoac OkHttp CertificatePinner de chan Proxy HTTP.",
        "suggestions": [
            "Nop (Xoa bo noi dung) phuong thuc `checkServerTrusted()` trong X509TrustManager",
            "Hook `CertificatePinner.check()` cua OkHttp de bo qua kiem tra SHA-256 cert",
            "Bo qua `HostnameVerifier.verify()` bang cach ep tra ve `true`",
        ],
    },
    "api_server_flow": {
        "label": "Luong goi API Server",
        "description": "Ung dung giao tiep voi Server qua HTTP/HTTPS de lay cau hinh hoac trang thai VIP.",
        "suggestions": [
            "Intercept HTTP response de override co config (vi du: `is_vip: true`)",
            "Sua logic parse JSON response luon gan gia tri VIP",
        ],
    },
    "manifest_res_check": {
        "label": "Xac minh Manifest & Tài nguyên",
        "description": "Ung dung doc Meta-Data tu AndroidManifest hoac co boolean tu Resources.",
        "suggestions": [
            "Patch co bool trong `res/values/bools.xml` sang true",
            "Hook `Resources.getBoolean()` tra ve true doi voi ID tai nguyen Pro",
        ],
    },
    "dependency_check": {
        "label": "Kiem tra phu thuoc & Moi truong",
        "description": "Ung dung kiem tra Google Play Services, framework he thong, moi truong Root, Magisk, Frida hoac Xposed.",
        "suggestions": [
            "Patch `isGooglePlayServicesAvailable()` luon tra ve SUCCESS (0x0)",
            "Bypass Root/Magisk check: Patch cac ham `isRooted()`, `checkSuBinary()` tra ve false (`const/4 v0, 0x0`)",
            "Xoa hoac vo hieu hoa logic kiem tra file binary nhay cam (`/sbin/su`, `/system/xbin/su`, `frida-server`)",
        ],
    },
    "remote_configuration": {
        "label": "Cau hinh tu may chu",
        "description": "Ung dung nhan du lieu tu mang va dung du lieu do de dieu khien hanh vi.",
        "suggestions": [
            "Intercept HTTP response de override co config",
            "Sua logic parse JSON response luon gan gia tri mong muon",
        ],
    },
    "location_usage": {
        "label": "Su dung vi tri",
        "description": "Ung dung truy cap hoac xu ly du lieu vi tri.",
        "suggestions": [
            "Mock Location bang cach override getLastKnownLocation tra ve toa do gia",
        ],
    },
    "permission_usage": {
        "label": "Su dung quyen",
        "description": "Ung dung su dung hoac yeu cau mot quyen Android.",
        "suggestions": [
            "Patch ham checkSelfPermission luon tra ve PERMISSION_GRANTED (0x0)",
        ],
    },
    "logging_usage": {
        "label": "Ghi log ung dung",
        "description": "Ung dung ghi log thông tin thuc thi qua android.util.Log.",
        "suggestions": [
            "Nop cac lệnh goi Log.d/v/i/e/w/wtf de loại bo log nhay cam",
        ],
    },
    "emulator_detection": {
        "label": "Phat hien may ao / Emulator",
        "description": "Ung dung kiem tra Build.FINGERPRINT, kernel qemu, goldfish, ranchu hoac nha san xuat may ao.",
        "suggestions": [
            "Hook Build.FINGERPRINT/Build.MODEL tra ve thiet bi that",
            "Patch nhanh so sanh chuoi `goldfish`, `ranchu`, `vbox86`, `nox`, `bluestacks`",
            "Spoof cac thuoc tinh `ro.kernel.qemu`, `ro.hardware`, `ro.product.brand`",
        ],
    },
    "anti_frida": {
        "label": "Chong Frida",
        "description": "Ung dung phat hien frida-server qua port 27042, tên thread `gum-js-loop` hoac cac chuoi `frida`/`gadget`.",
        "suggestions": [
            "Doi cong frida-server trước khi inject",
            "Patch ham quet port 27042 hoac so sanh chuoi `frida`",
            "Dung che do `--no-pause`/spawn som va an tien trinh frida",
        ],
    },
    "anti_hook": {
        "label": "Chong Hook / Xposed",
        "description": "Ung dung phat hien XposedBridge, LSPosed, Substrate hoac cac framework hook trong stacktrace/classloader.",
        "suggestions": [
            "An module Xposed/LSPosed khối process mức tieu",
            "Patch class kiem tra `de.robv.android.xposed` hoac `XposedBridge`",
            "Dung Frida gadget thay vi Xposed de giam dau vet",
        ],
    },
    "root_detection": {
        "label": "Phat hien Root / SU",
        "description": "Ung dung kiem tra file `su`, Magisk, Superuser.apk, `which su` hoac build tag `test-keys`.",
        "suggestions": [
            "Patch `isRooted()`, `checkSuBinary()` tra ve false",
            "An root bang Magisk DenyList/Shamiko cho package mức tieu",
            "Hook `File.exists()` de chan cac duong dan `/sbin/su`, `/system/xbin/su`",
        ],
    },
    "tamper_detection": {
        "label": "Phat hien APK bi chinh sua",
        "description": "Ung dung so sanh chu ky APK, CRC, hash DEX hoac thoi gian cai đạt de phat hien ban mod.",
        "suggestions": [
            "Hook PackageManager.getPackageInfo tra ve chu ky goc",
            "Patch nhanh so sanh SHA/CRC that bai",
            "Dung Frida de mo phong certificate/Signature goc",
        ],
    },
    "time_based_check": {
        "label": "Kiem tra thoi gian / het han",
        "description": "Ung dung so sanh `System.currentTimeMillis()`, thoi gian server hoac ngay het han de khoa/mo tinh nang.",
        "suggestions": [
            "Hook `currentTimeMillis()`, `Date.getTime()` tra ve moc thoi gian hop le",
            "Patch nhanh `if-lt/if-ge` so sanh thoi gian het han",
            "Overwrite response chua `expires_at`, `expired`, `deadline`",
        ],
    },
    "dynamic_code_loading": {
        "label": "Nap ma dong",
        "description": "Ung dung dung DexClassLoader/PathClassLoader hoac nap dex/jar/so tai runtime.",
        "suggestions": [
            "Hook `DexClassLoader` de dump DEX trước khi load",
            "Theo doi `dalvik.system.PathClassLoader` va ghi nguon payload",
            "Chan ClassLoader neu nguon den tu server khong tin cây",
        ],
    },
    "reflection_usage": {
        "label": "Dung Reflection",
        "description": "Ung dung goi method/field thong qua reflection, thuong dung de an luong kiem tra bao ve.",
        "suggestions": [
            "Hook `java.lang.reflect.Method.invoke` de log class/method/args",
            "Theo doi `Class.forName` va `getDeclaredMethod`",
            "Phan tich stacktrace tim điểm goi reflection nghi ngo",
        ],
    },
    "native_library_check": {
        "label": "Kiem tra Native Library",
        "description": "Ung dung dung JNI hoac kiem tra su ton tai/tinh hop le cua file `.so`.",
        "suggestions": [
            "Hook `System.loadLibrary`/`Runtime.loadLibrary0` de map Java method sang native",
            "Dung Frida Interceptor de hook JNI_OnLoad va native check",
            "Patch file `.so` neu can thay doi nhanh native",
        ],
    },
    "webview_js_bridge": {
        "label": "Bridge WebView / JavaScript",
        "description": "Ung dung dung WebView va addJavascriptInterface/evaluateJavascript de giao tiep voi noi dung web.",
        "suggestions": [
            "Hook `addJavascriptInterface` de kiem tra object bi expose",
            "Log message `evaluateJavascript`/`postMessage`",
            "Kiem tra URL scheme va noi dung tai ve trước khi render",
        ],
    },
    "clipboard_monitoring": {
        "label": "Giam sat Clipboard",
        "description": "Ung dung doc/ghi ClipboardManager hoac lầng nghe thay doi clipboard.",
        "suggestions": [
            "Hook `getPrimaryClip`/`setPrimaryClip` de kiem soat du lieu",
            "Xoa du lieu nhay cam sau khi app doc clipboard",
            "Theo doi `addPrimaryClipChangedListêner`",
        ],
    },
    "screen_capture_detection": {
        "label": "Chong chup man hinh",
        "description": "Ung dung dung FLAG_SECURE hoac phat hien anh chup man hinh de an noi dung nhay cam.",
        "suggestions": [
            "Hook `Window.setFlags` de bo `FLAG_SECURE`",
            "Patch hang so `WindowManager.LayoutParams.FLAG_SECURE` khi set",
            "Vo hieu hoa logic an noi dung khi co screenshot",
        ],
    },
    "keystore_key_usage": {
        "label": "Dung Android Keystore",
        "description": "Ung dung dung AndroidKeyStore/KeyGenerator/KeyPairGenerator de tao hoac ky du lieu.",
        "suggestions": [
            "Hook `KeyStore.load`/`getKey` de log alias va key type",
            "Theo doi `KeyGenerator.generateKey`/`KeyPairGenerator.generateKeyPair`",
            "Dump key material neu app dung software fallback",
        ],
    },
    "backup_restore_check": {
        "label": "Kiem tra Backup / Restore",
        "description": "Ung dung cau hinh allowBackup/FullBackupContênt hoac dung BackupManager de luu/phuc hoi trang thai.",
        "suggestions": [
            "Patch `allowBackup=false` trong AndroidManifest neu can chan backup",
            "Hook BackupManager/dataChanged de theo doi du lieu dong bo",
            "Kiem tra rules `full-backup-content` trước khi xu ly du lieu",
        ],
    },
    "cryptographic_operations": {
        "label": "Ma hoa / Giai ma",
        "description": "Ung dung dung Cipher, MessageDigest, MAC hoac KeyGenerator cho du lieu nhay cam.",
        "suggestions": [
            "Hook `Cipher.doFinal` de bat plaintext/ciphertext",
            "Log `MessageDigest.digest` va `Mac.doFinal`",
            "Tim key hardcode bang cach theo doi SecretKeySpec/KeyGenerator",
        ],
    },
}
