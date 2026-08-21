from __future__ import annotations


class CryptoInterceptorGenerator:
    """Tao Frida Script theo doi va giai ma du lieu ma hoa HTTP/Crypto tu xa."""

    @staticmethod
    def generate_crypto_hooks() -> str:
        return """
    // =====================================================
    // CRYPTO INTERCEPTOR & DECRYPTION MONITOR
    // =====================================================
    try {
        var Cipher = Java.use('javax.crypto.Cipher');
        var SecretKeySpec = Java.use('javax.crypto.spec.SecretKeySpec');
        var StringClass = Java.use('java.lang.String');

        // Hook Cipher.doFinal(byte[]) de bat du lieu Truoc/Sau giai ma
        Cipher.doFinal.overload('[B').implementation = function (input) {
            var result = this.doFinal(input);
            try {
                var mode = this.getOptmode(); // 1 = ENCRYPT, 2 = DECRYPT
                var algo = this.getAlgorithm();
                var plainText = StringClass.$new(mode === 2 ? result : input);
                
                console.log('[CRYPTO] Algo: ' + algo + ' | Mode: ' + (mode === 2 ? 'DECRYPT' : 'ENCRYPT'));
                console.log('[CRYPTO] Data: ' + plainText.toString());

                if (plainText.contains('"is_vip"') || plainText.contains('"status"') || plainText.contains('"config"')) {
                    console.log('[!] PHAT HIEN PAYLOAD CAU HINH TU XA: ' + plainText);
                    send({ type: 'CRYPTO_PAYLOAD_DETECTED', algo: algo, payload: plainText.toString() });
                }
            } catch (e) {}
            return result;
        };
        console.log('[+] Crypto Interceptor Hooked Successfully');
    } catch (err) {
        console.log('[-] Crypto Hook Error: ' + err);
    }
"""
