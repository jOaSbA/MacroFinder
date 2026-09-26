package com.macrofinder.app.data.following

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.macrofinder.app.MainActivity
import com.macrofinder.app.R
import com.macrofinder.app.data.catalogue.Deal
import com.macrofinder.app.ui.fmt

/**
 * Posts "a product you follow is on offer". Default importance, so Do Not
 * Disturb and the system's quiet hours apply without the app doing anything.
 */
object PromoNotifier {
    private const val CHANNEL = "followed-promos"

    fun post(context: Context, deals: List<Deal>) {
        if (deals.isEmpty() || !allowed(context)) return
        createChannel(context)
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val title = if (deals.size == 1) "${deals[0].name} is in de aanbieding"
        else "${deals.size} gevolgde producten in de aanbieding"
        val body = deals.take(5).joinToString("\n") { d ->
            listOfNotNull(d.name, d.promoText, d.price?.let { fmt("€%.2f", it) }).joinToString(" · ")
        }
        val notification = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_tag)
            .setContentTitle(title)
            .setContentText(body.lineSequence().first())
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(1, notification)
        } catch (_: SecurityException) {
            // Permission revoked between the check and the post.
        }
    }

    fun allowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(
            context, Manifest.permission.POST_NOTIFICATIONS,
        ) == PackageManager.PERMISSION_GRANTED

    private fun createChannel(context: Context) {
        val manager = context.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(
            NotificationChannel(CHANNEL, "Gevolgde producten", NotificationManager.IMPORTANCE_DEFAULT)
                .apply { description = "Als een product dat je volgt in de aanbieding gaat" },
        )
    }
}
