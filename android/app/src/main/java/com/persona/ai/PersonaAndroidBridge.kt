package com.persona.ai

import android.util.Log
import android.webkit.JavascriptInterface
import com.chaquo.python.Python

/** WebView → native: BYOK sync + Raja Mop laugh track. */
class PersonaAndroidBridge(
    private val activity: MainActivity,
    private val byokStore: ByokStore,
    private val papuaAiViewModel: PapuaAiViewModel,
    private val conversationModeStore: ConversationModeStore,
) {
    /** Reliable button path on Android WebView — round-trip ke JS action handler. */
    @JavascriptInterface
    fun uiTap(actionId: String) {
        val action = actionId.trim()
        if (action.isEmpty()) return
        activity.runOnUiThread { activity.runWebUiAction(action) }
    }

    @JavascriptInterface
    fun setApiKey(key: String) {
        val trimmed = key.trim()
        if (trimmed.length < 8) return
        activity.runOnUiThread {
            if (byokStore.hasApiKey()) return@runOnUiThread
            byokStore.setApiKey(trimmed)
            Log.i(TAG, "API key synced from web (store was empty)")
            LocalPersonaServer.start(activity, trimmed)
        }
    }

    @JavascriptInterface
    fun hasApiKey(): Boolean = byokStore.hasApiKey()

    /** Dipanggil dari live.js saat turn_complete + laugh_track (punchline mop selesai). */
    @JavascriptInterface
    fun playLaughTrack() {
        activity.runOnUiThread {
            papuaAiViewModel.onLiveTurnComplete(laughTrack = true)
        }
    }

    @JavascriptInterface
    fun startBgm(mode: String) {
        activity.runOnUiThread {
            papuaAiViewModel.startBgm(mode)
        }
    }

    @JavascriptInterface
    fun stopBgm() {
        activity.runOnUiThread {
            papuaAiViewModel.stopBgm()
        }
    }

    @JavascriptInterface
    fun playJedagJedug() {
        activity.runOnUiThread {
            papuaAiViewModel.playJedagJedug()
        }
    }

    @JavascriptInterface
    fun setDailyRemindersEnabled(enabled: Boolean) {
        CheckInScheduler.setRemindersEnabled(activity.applicationContext, enabled)
    }

    @JavascriptInterface
    fun getDailyRemindersEnabled(): Boolean {
        return CheckInScheduler.remindersEnabled(activity.applicationContext)
    }

    /** Saat app/WebView ke background — sama dengan POST /api/session/.../extract-memory */
    @JavascriptInterface
    fun finalizeSessionMemory(sessionId: String?) {
        SessionMemoryExtract.finalizeSession(sessionId)
    }

    /**
     * Experience mode dari strip UI premium (Chaquopy → webview_bridge → live_session_hub).
     * Jalur utama mid-call tetap WebSocket ``conversation_mode``; ini fallback + persist native.
     */
    @JavascriptInterface
    fun onModeChanged(newMode: String) {
        val raw = newMode.trim()
        if (raw.isEmpty()) return
        conversationModeStore.setMode(raw)
        Thread {
            try {
                val bridge = Python.getInstance().getModule("persona_ai.plugins.webview_bridge")
                val result = bridge.callAttr("handle_ui_mode_change", raw)
                Log.i(TAG, "onModeChanged raw=$raw py=$result")
            } catch (e: Exception) {
                Log.e(TAG, "onModeChanged failed raw=$raw", e)
            }
        }.start()
    }

    companion object {
        private const val TAG = "PersonaAndroid"
    }
}
