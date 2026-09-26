package com.macrofinder.app.data.catalogue

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** Milestone 37. The same cases as tests/test_gtin.py. */
class BarcodeTest {
    @Test
    fun `valid codes come back as the catalogue stores them`() {
        assertEquals("8718452994274", normaliseBarcode("8718452994274"))
        assertEquals("8710400241645", normaliseBarcode("08710400241645"))
        assertEquals("96385074", normaliseBarcode("96385074"))
        assertEquals("0036000291452", normaliseBarcode("036000291452"))
    }

    @Test
    fun `misreads and other codes are null`() {
        assertNull(normaliseBarcode("8718452994275"))
        assertNull(normaliseBarcode("https://example.com"))
        assertNull(normaliseBarcode("12345"))
        assertNull(normaliseBarcode(null))
    }
}
