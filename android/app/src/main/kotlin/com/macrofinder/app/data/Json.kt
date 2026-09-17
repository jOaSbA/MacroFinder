package com.macrofinder.app.data

import kotlinx.serialization.json.Json

/**
 * One shared decoder. `ignoreUnknownKeys` matters here specifically: the
 * Python export is versioned (`schema_version`) but this app is not rebuilt
 * every time a new field is added on that side, so an unrecognised key must
 * never crash decoding.
 */
val MacroFinderJson: Json = Json {
    ignoreUnknownKeys = true
    isLenient = true
}

fun parseSnapshot(jsonText: String): ExportSnapshot =
    MacroFinderJson.decodeFromString(ExportSnapshot.serializer(), jsonText)
