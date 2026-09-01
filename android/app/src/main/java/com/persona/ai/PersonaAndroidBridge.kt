package com.persona.ai

import android.util.Log
import android.webkit.JavascriptInterface

/** WebView → native: BYOK sync + Raja Mop laugh track. */
class PersonaAndroidBridge(
    private val activity: MainActivity,
    private val byokStore: ByokStore,
    private val papuaAiViewModel: PapuaAiViewModel,
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
            PersonaServerService.start(activity, trimmed)
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

    companion object {
        private const val TAG = "PersonaAndroid"
    }
}
