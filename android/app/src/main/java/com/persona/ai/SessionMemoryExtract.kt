package com.persona.ai

import android.util.Log
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/** Fire-and-forget post-call memory extract on local Persona server. */
object SessionMemoryExtract {
    private const val TAG = "SessionMemoryExtract"

    fun finalizeSession(sessionId: String?) {
        val id = sessionId?.trim().orEmpty()
        if (id.length < 2 || id.length > 128) return
        Thread {
            try {
                val encoded = URLEncoder.encode(id, StandardCharsets.UTF_8.name())
                val url = URL("${LocalPersonaServer.LOCAL_BASE_URL}api/session/$encoded/extract-memory")
                val conn = url.openConnection() as HttpURLConnection
                conn.connectTimeout = 8000
                conn.readTimeout = 120_000
                conn.requestMethod = "POST"
                val code = conn.responseCode
                conn.disconnect()
                Log.i(TAG, "extract-memory session=$id http=$code")
            } catch (e: Exception) {
                Log.w(TAG, "extract-memory failed session=$id", e)
            }
        }.start()
    }
}
