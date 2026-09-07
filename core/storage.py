def public_media_backend(use_cloudinary):
    return (
        "cloudinary_storage.storage.MediaCloudinaryStorage"
        if use_cloudinary
        else "django.core.files.storage.FileSystemStorage"
    )
