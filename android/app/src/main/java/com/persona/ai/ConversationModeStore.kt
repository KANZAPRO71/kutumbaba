package com.persona.ai

import android.content.Context

/** Persist experience mode id from WebView (mirrors localStorage key). */
class ConversationModeStore(context: Context) {

    private val prefs =
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    fun getMode(): String? = prefs.getString(KEY, null)?.trim()?.takeIf { it.isNotEmpty() }

    fun setMode(modeId: String) {
        val trimmed = modeId.trim()
        if (trimmed.isEmpty()) return
        prefs.edit().putString(KEY, trimmed).apply()
    }

    companion object {
        private const val PREFS = "papua_ai_prefs"
        private const val KEY = "papua_conversation_mode"
    }
}
