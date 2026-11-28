package nl.c4w.stroom.boox.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Bewaart alleen de sessiecookie, nooit het wachtwoord. */
interface SessionStore {
    fun read(account: String): String?
    fun save(account: String, value: String)
    fun delete(account: String)
}

class MemorySessionStore : SessionStore {
    private val values = mutableMapOf<String, String>()
    override fun read(account: String) = values[account]
    override fun save(account: String, value: String) {
        values[account] = value
    }
    override fun delete(account: String) {
        values.remove(account)
    }
}

/**
 * De cookie wordt versleuteld met een AES-sleutel in de Android Keystore. Die sleutel
 * verlaat het apparaat niet; een back-up of gekopieerde app-map is daarmee onbruikbaar.
 */
class KeystoreSessionStore(context: Context) : SessionStore {
    private val prefs = context.getSharedPreferences("session", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    override fun read(account: String): String? {
        val stored = prefs.getString(account, null) ?: return null
        return runCatching {
            val bytes = Base64.decode(stored, Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, bytes, 0, IV_SIZE))
            String(cipher.doFinal(bytes, IV_SIZE, bytes.size - IV_SIZE), Charsets.UTF_8)
        }.getOrElse {
            delete(account)
            null
        }
    }

    override fun save(account: String, value: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        val sealed = cipher.iv + cipher.doFinal(value.toByteArray(Charsets.UTF_8))
        prefs.edit().putString(account, Base64.encodeToString(sealed, Base64.NO_WRAP)).apply()
    }

    override fun delete(account: String) {
        prefs.edit().remove(account).apply()
    }

    private companion object {
        const val ALIAS = "stroom_session_key"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_SIZE = 12
    }
}
