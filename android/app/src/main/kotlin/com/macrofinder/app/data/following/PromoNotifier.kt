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
import com.macrofinder.app.ui.theme.chainName

/**
 * Posts "a product you follow is on offer". Default importance, so Do Not
 * Disturb and the system's quiet hours apply without the app doing anything.
 */
object PromoNotifier {
    private const val CHANNEL = "followed-promos"
    private const val DIGEST_CHANNEL = "weekly-digest"

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

    /** Milestone 34: followed products that dropped under their price target. */
    fun postTargets(context: Context, deals: List<Deal>) {
        if (deals.isEmpty() || !allowed(context)) return
        createChannel(context)
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val title = if (deals.size == 1) "${deals[0].name} is onder je doelprijs"
        else "${deals.size} producten onder je doelprijs"
        val body = deals.take(5).joinToString("\n") { d ->
            val mark = if (d.macrosEstimated) "≈ " else ""
            listOfNotNull(d.name, d.eurPer100gProtein?.let { mark + fmt("€%.2f per 100 g eiwit", it) })
                .joinToString(" · ")
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
            NotificationManagerCompat.from(context).notify(3, notification)
        } catch (_: SecurityException) {
        }
    }

    /** Milestone 33: the weekly digest, on its own channel so it can be muted alone. */
    fun postDigest(context: Context, deals: List<Deal>) {
        if (deals.isEmpty() || !allowed(context)) return
        context.getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(DIGEST_CHANNEL, "Wekelijks overzicht", NotificationManager.IMPORTANCE_LOW)
                .apply { description = "De goedkoopste eiwitaanbiedingen van de week" },
        )
        val open = PendingIntent.getActivity(
            context, 0,
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        val body = deals.joinToString("\n") { d ->
            val mark = if (d.macrosEstimated) "≈ " else ""
            listOfNotNull(d.name, chainName(d.chain), d.eurPer100gProtein?.let { mark + fmt("€%.2f per 100 g eiwit", it) })
                .joinToString(" · ")
        }
        val notification = NotificationCompat.Builder(context, DIGEST_CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_tag)
            .setContentTitle("Goedkoop eiwit deze week")
            .setContentText(body.lineSequence().first())
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(open)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        try {
            NotificationManagerCompat.from(context).notify(2, notification)
        } catch (_: SecurityException) {
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
