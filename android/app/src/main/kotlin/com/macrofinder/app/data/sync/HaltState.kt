package com.macrofinder.app.data.sync

import android.content.Context

/**
 * Whether the publisher has pulled the kill switch (milestone 30), and what it
 * said. Kept in preferences because WorkManager forgets a periodic job's output
 * the moment it is re-enqueued, which would show the message once and lose it.
 */
object HaltState {
    private const val PREFS = "sync"
    private const val KEY = "halt_message"
    private const val DEFAULT = "De catalogus wordt op dit moment niet bijgewerkt. " +
        "Je ziet de gegevens van de laatste keer."

    fun set(context: Context, message: String?) = prefs(context).edit()
        .putString(KEY, message?.takeIf { it.isNotBlank() } ?: DEFAULT).apply()

    fun clear(context: Context) = prefs(context).edit().remove(KEY).apply()

    fun message(context: Context): String? = prefs(context).getString(KEY, null)

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
}
