package com.productionreview.mobile

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.exifinterface.media.ExifInterface
import java.io.File
import java.io.FileOutputStream

internal object PhotoCompressor {
    /** Creates an oriented, size-limited JPEG copy for upload; the original remains available for retry. */
    fun prepare(source: File): File {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(source.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            throw IllegalArgumentException("The camera did not produce a readable photograph.")
        }

        var sample = 1
        while (bounds.outWidth / sample > 1920 || bounds.outHeight / sample > 1920) sample *= 2
        val options = BitmapFactory.Options().apply { inSampleSize = sample }
        val decoded = BitmapFactory.decodeFile(source.absolutePath, options)
            ?: throw IllegalArgumentException("Unable to read the captured photograph.")

        val orientation = runCatching { ExifInterface(source).getAttributeInt(
            ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL
        ) }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
        val matrix = Matrix().apply {
            when (orientation) {
                ExifInterface.ORIENTATION_ROTATE_90 -> postRotate(90f)
                ExifInterface.ORIENTATION_ROTATE_180 -> postRotate(180f)
                ExifInterface.ORIENTATION_ROTATE_270 -> postRotate(270f)
                ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> postScale(-1f, 1f)
                ExifInterface.ORIENTATION_FLIP_VERTICAL -> postScale(1f, -1f)
            }
        }
        val bitmap = if (orientation != ExifInterface.ORIENTATION_NORMAL) {
            Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true).also {
                if (it !== decoded) decoded.recycle()
            }
        } else decoded

        val output = File(source.parentFile, source.nameWithoutExtension + "_upload.jpg")
        try {
            FileOutputStream(output).use { stream ->
                if (!bitmap.compress(Bitmap.CompressFormat.JPEG, 82, stream)) {
                    throw IllegalStateException("Unable to prepare the photograph for upload.")
                }
            }
        } catch (error: Exception) {
            output.delete()
            throw error
        } finally {
            bitmap.recycle()
        }
        if (output.length() > 8L * 1024L * 1024L) {
            output.delete()
            throw IllegalStateException("The compressed photograph is still larger than 8 MB.")
        }
        return output
    }
}
