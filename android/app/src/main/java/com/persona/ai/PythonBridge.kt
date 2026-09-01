package com.persona.ai

import android.util.Log
import com.chaquo.python.Python

object PythonBridge {

    private const val TAG = "PythonBridge"

    @Volatile
    var lastStartError: String? = null
        private set

    fun startServer(host: String, port: Int, apiKey: String, filesDir: String): Boolean {
        lastStartError = null
        return try {
            val module = Python.getInstance().getModule("persona_ai.android.bootstrap")
            val result = module.callAttr("start_server", host, port, apiKey, filesDir)
            result?.toBoolean() ?: false
        } catch (e: Exception) {
            lastStartError = e.message ?: e.javaClass.simpleName
            Log.e(TAG, "Failed to start embedded Python server", e)
            false
        }
    }
}
