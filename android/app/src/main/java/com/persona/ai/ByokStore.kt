package com.persona.ai

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * GEMINI_API_KEY on device.
 *
 * POLICY: Never delete or overwrite with empty/invalid values.
 * Plain prefs are source of truth (Vivo-safe); encrypted copy is best-effort.
 */
class ByokStore(context: Context) {

    private val appContext = context.applicationContext
    private val plainPrefs: SharedPreferences =
        appContext.getSharedPreferences(PLAIN_PREFS_NAME, Context.MODE_PRIVATE)
    private val encryptedPrefs: SharedPreferences? = openEncryptedPrefs(appContext)

    init {
        migrateFromEncryptedIfNeeded()
    }

    fun getApiKey(): String {
        val plain = readKey(plainPrefs)
        if (plain.length >= MIN_KEY_LEN) {
            return plain
        }
        val encrypted = readKey(encryptedPrefs)
        if (encrypted.length >= MIN_KEY_LEN) {
            savePlain(encrypted)
            Log.i(TAG, "recovered API key from encrypted store into plain backup")
            return encrypted
        }
        return ""
    }

    /** Save key — refuses empty/short values; never clears an existing key. */
    fun setApiKey(key: String) {
        val trimmed = key.trim()
        if (trimmed.length < MIN_KEY_LEN) {
            Log.w(TAG, "ignored invalid API key write — existing key preserved")
            return
        }
        savePlain(trimmed)
        encryptedPrefs?.edit()?.putString(KEY_GEMINI_API_KEY, trimmed)?.commit()
    }

    fun hasApiKey(): Boolean = getApiKey().length >= MIN_KEY_LEN

    /** Seed from project .env only when device store is empty. Never replaces existing key. */
    fun seedFromProjectEnv(key: String) {
        if (hasApiKey()) return
        val trimmed = key.trim()
        if (trimmed.length >= MIN_KEY_LEN) {
            setApiKey(trimmed)
            Log.i(TAG, "seeded API key from project .env (web)")
        }
    }

    private fun migrateFromEncryptedIfNeeded() {
        if (readKey(plainPrefs).length >= MIN_KEY_LEN) return
        val encrypted = readKey(encryptedPrefs)
        if (encrypted.length >= MIN_KEY_LEN) {
            savePlain(encrypted)
            Log.i(TAG, "migrated API key from encrypted to plain on startup")
        }
    }

    private fun savePlain(key: String) {
        if (key.length < MIN_KEY_LEN) {
            Log.w(TAG, "refused to clear API key")
            return
        }
        plainPrefs.edit().putString(KEY_GEMINI_API_KEY, key).commit()
    }

    private fun readKey(prefs: SharedPreferences?): String {
        return prefs?.getString(KEY_GEMINI_API_KEY, "")?.trim().orEmpty()
    }

    companion object {
        private const val TAG = "ByokStore"
        private const val ENCRYPTED_PREFS_NAME = "persona_byok_secure"
        private const val PLAIN_PREFS_NAME = "persona_byok_backup"
        private const val KEY_GEMINI_API_KEY = "gemini_api_key"
        private const val MIN_KEY_LEN = 8

        private fun openEncryptedPrefs(context: Context): SharedPreferences? {
            return try {
                val masterKey = MasterKey.Builder(context)
                    .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                    .build()
                EncryptedSharedPreferences.create(
                    context,
                    ENCRYPTED_PREFS_NAME,
                    masterKey,
                    EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                    EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
                )
            } catch (e: Exception) {
                Log.w(TAG, "encrypted prefs unavailable", e)
                null
            }
        }
    }
}
