"""Vault-backed organisation store for the pinned org_intake capability."""
from careeros import vault


class VaultOrganisationStore:
    """Use existing company keys and the ordinary vault merge/save path.

    Organisation fields already use the same keys as company records.
    The vault retains product fields and replaces supplied lists wholesale.
    Callers retain responsibility for the product write lock.
    """

    def __init__(self, root):
        self.root = root

    def list_organisations(self):
        return vault.list_companies(self.root)

    def load_organisation(self, organisation_id):
        return vault.load_company(self.root, organisation_id)

    def save_organisation(self, updates, organisation_id=None):
        return vault.save_company(self.root, updates, organisation_id)
