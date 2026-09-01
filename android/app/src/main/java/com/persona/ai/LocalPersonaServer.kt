package com.persona.ai

import android.content.Context
import android.util.Log
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit

/**
 * Starts Persona backend on-device (BYOK). Uses Chaquopy embedded Python when available.
 */
object LocalPersonaServer {

    private const val TAG = "PersonaLocalServer"
    const val LOCAL_HOST = "127.0.0.1"
    const val LOCAL_PORT = 8765
    const val LOCAL_BASE_URL = "http://$LOCAL_HOST:$LOCAL_PORT/"

    private val executor = Executors.newSingleThreadExecutor()
    private var startFuture: Future<*>? = null
    @Volatile
    private var started = false

    fun start(context: Context, apiKey: String): Boolean {
        if (started && isHealthy()) {
            return true
        }
        val filesDir = context.filesDir.absolutePath
        startFuture?.cancel(true)
        startFuture = executor.submit {
            try {
                ensurePythonStarted(context)
                if (!PythonBridge.startServer(LOCAL_HOST, LOCAL_PORT, apiKey, filesDir)) {
                    Log.e(TAG, "Python backend failed to start")
                    started = false
                    return@submit
                }
                started = waitForHealth(LOCAL_HOST, LOCAL_PORT, 60_000)
                Log.i(TAG, "Local server ready=$started")
            } catch (e: Exception) {
                Log.e(TAG, "Local server error", e)
                started = false
            }
        }
        return true
    }

    fun waitUntilReady(timeoutMs: Long = 45_000): Boolean {
        startFuture?.get(timeoutMs.coerceAtMost(120_000), TimeUnit.MILLISECONDS)
        return isHealthy()
    }

    fun isHealthy(): Boolean {
        return waitForHealth(LOCAL_HOST, LOCAL_PORT, 1_500)
    }

    private fun waitForHealth(host: String, port: Int, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (pingHealth(host, port)) {
                started = true
                return true
            }
            Thread.sleep(250)
        }
        return false
    }

    private fun pingHealth(host: String, port: Int): Boolean {
        return try {
            val conn = URL("http://$host:$port/api/health").openConnection() as HttpURLConnection
            conn.connectTimeout = 1500
            conn.readTimeout = 1500
            conn.requestMethod = "GET"
            val ok = conn.responseCode == 200
            conn.disconnect()
            ok
        } catch (_: Exception) {
            false
        }
    }

    /**
     * Chaquopy treats the Python.start() thread as the interpreter main thread.
     * Gemini Live asyncio must run there — not on the Android UI thread.
     */
    private fun ensurePythonStarted(context: Context) {
        if (Python.isStarted()) return
        Python.start(AndroidPlatform(context.applicationContext))
        Log.i(TAG, "Chaquopy Python started on backend thread")
    }
}
