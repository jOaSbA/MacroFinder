package com.macrofinder.app

import android.app.Application
import coil.ImageLoader
import coil.ImageLoaderFactory
import okhttp3.OkHttpClient

/**
 * Sends an honest User-Agent with every image request. Jumbo's CDN resets the
 * connection for the stock "okhttp/x" agent but serves an app that says what
 * it is. Same rule as the scraper: identify, never pretend to be a browser.
 */
class MacroFinderApplication : Application(), ImageLoaderFactory {
    override fun newImageLoader(): ImageLoader {
        val client = OkHttpClient.Builder()
            .addInterceptor { chain ->
                chain.proceed(chain.request().newBuilder()
                    .header("User-Agent", "MacroFinder/${BuildConfig.VERSION_NAME} (Android)")
                    .build())
            }
            .build()
        return ImageLoader.Builder(this).okHttpClient(client).crossfade(false).build()
    }
}
