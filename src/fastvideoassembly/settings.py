"""Settings interface for sessions that neither restore nor save state."""


class NoProfileSettings:
    def value(self, key, defaultValue=None, type=None):
        return defaultValue

    def contains(self, key):
        return False

    def setValue(self, key, value):
        pass

    def remove(self, key):
        pass

    def beginReadArray(self, prefix):
        return 0

    def beginWriteArray(self, prefix, size=-1):
        pass

    def setArrayIndex(self, index):
        pass

    def endArray(self):
        pass

    def sync(self):
        pass
