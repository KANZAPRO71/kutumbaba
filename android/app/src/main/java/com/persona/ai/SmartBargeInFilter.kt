package com.persona.ai

/**
 * Smart Barge-In filter (Papua) — mirror logika Python/JS.
 * Interupsi audio RMS saja ditolak; hanya frasa penantang jelas yang lolos.
 */
object SmartBargeInFilter {

    const val MIN_CHALLENGE_DURATION_MS = 800L

    private val fillerOnly = setOf(
        "iyo", "iya", "ah", "eh", "ehem", "oh", "hmm", "ee", "toh", "kah",
    )

    private val challengePhrases = listOf(
        "ko tipu",
        "ko bohong",
        "stop sudah",
        "sudah cukup",
        "ganti mop",
        "tra lucu",
        "tra percaya",
        "bohong",
        "tipu sa",
        "diam sudah",
        "mop lain",
        "mop baru",
    )

    fun isFillerOnly(text: String?): Boolean {
        val q = text?.trim()?.lowercase() ?: return true
        if (q.isEmpty()) return true
        val words = q.split(Regex("\\W+")).filter { it.isNotBlank() }
        if (words.size == 1 && words[0] in fillerOnly) return true
        return q.length <= 4 && q in fillerOnly
    }

    fun isChallengeInterrupt(text: String?): Boolean {
        val q = text?.trim()?.lowercase() ?: return false
        if (q.isEmpty()) return false
        return challengePhrases.any { q.contains(it) }
    }

    /** Boleh potong AI jika durasi >= 0.8s dan teks penantang jelas. */
    fun shouldAllowBargeIn(transcript: String?, durationMs: Long): Boolean {
        if (isFillerOnly(transcript)) return false
        if (durationMs in 1 until MIN_CHALLENGE_DURATION_MS) return false
        return isChallengeInterrupt(transcript)
    }
}
