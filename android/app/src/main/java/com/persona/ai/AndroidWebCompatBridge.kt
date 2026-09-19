package com.persona.ai

import android.webkit.JavascriptInterface

/** Blueprint alias ``window.Android`` → [PersonaAndroidBridge]. */
class AndroidWebCompatBridge(
    private val personaBridge: PersonaAndroidBridge,
) {
    @JavascriptInterface
    fun onModeChanged(newMode: String) {
        personaBridge.onModeChanged(newMode)
    }
}
