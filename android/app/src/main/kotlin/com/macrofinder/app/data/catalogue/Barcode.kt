package com.macrofinder.app.data.catalogue

/**
 * Milestone 37: what the scanner read, as the catalogue stores it. Same rules
 * as `parsers/gtin.py`: a valid GS1 check digit, GTIN-14 padding stripped,
 * UPC-A widened to 13 digits, EAN-8 kept. Null for anything else, such as a
 * QR code or a misread.
 */
fun normaliseBarcode(raw: String?): String? {
    val code = raw?.trim() ?: return null
    if (!code.all(Char::isDigit) || code.length !in setOf(8, 12, 13, 14)) return null
    val digits = code.map { it - '0' }
    val body = digits.dropLast(1).reversed()
    val sum = body.withIndex().sumOf { (i, d) -> if (i % 2 == 0) d * 3 else d }
    if ((10 - sum % 10) % 10 != digits.last()) return null
    return when {
        code.length == 14 && code.startsWith("0") -> code.drop(1)
        code.length == 12 -> "0$code"
        else -> code
    }
}
