from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage, Storage
from django.utils.deconstruct import deconstructible


@deconstructible
class PrivateVerificationStorage(Storage):
    def __init__(self, *args, **kwargs):
        self.local = FileSystemStorage(location=settings.VERIFICATION_DOCUMENT_ROOT, base_url=None)

    @property
    def cloudinary_enabled(self):
        return getattr(settings, "USE_CLOUDINARY", False)

    def _save(self, name, content):
        if not self.cloudinary_enabled:
            return self.local.save(name, content)
        import cloudinary.uploader

        public_id = name.rsplit(".", 1)[0]
        result = cloudinary.uploader.upload(
            content, public_id=public_id, resource_type="raw", type="authenticated", overwrite=False
        )
        return result["public_id"] + (f'.{result["format"]}' if result.get("format") else "")

    def _open(self, name, mode="rb"):
        if not self.cloudinary_enabled:
            return self.local.open(name, mode)
        import requests
        from cloudinary.utils import private_download_url

        stem, separator, extension = name.rpartition(".")
        response = requests.get(
            private_download_url(
                stem if separator else name, extension if separator else None, resource_type="raw", type="authenticated"
            ),
            timeout=20,
        )
        response.raise_for_status()
        return ContentFile(response.content, name=name)

    def delete(self, name):
        if not self.cloudinary_enabled:
            return self.local.delete(name)
        import cloudinary.uploader

        stem = name.rsplit(".", 1)[0]
        cloudinary.uploader.destroy(stem, resource_type="raw", type="authenticated", invalidate=True)

    def exists(self, name):
        if not self.cloudinary_enabled:
            return self.local.exists(name)
        return False

    def url(self, name):
        raise ValueError("Verification documents do not expose public URLs.")

    def size(self, name):
        if not self.cloudinary_enabled:
            return self.local.size(name)
        return 0


private_verification_storage = PrivateVerificationStorage()
