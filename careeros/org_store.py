"""Vault-backed organisation store for the pinned org_intake capability."""
from careeros import vault


class CompanyCreationDenied(Exception):
    """The resolution ladder wanted to create a company and may not.

    M2 (CAREER-39, decision D3): a company is shared universe, and
    bringing one into existence is a write to the shared half, so it is
    the admin's. The capability decides to create inside
    `org_intake.identity.resolve_identity`, which this product does not
    edit (it is a pinned vendor dependency), and it creates by calling
    `save_organisation` with no id. That is the one place the boundary
    can be drawn without touching the capability, so it is drawn here:
    the store refuses, and `server.resolve_company` turns the refusal
    into the ordinary pending answer. Nothing is written before the
    refusal, because every other write the ladder makes carries an id
    and is a no-op on a read-only store.
    """


class VaultOrganisationStore:
    """Use existing company keys and the ordinary vault merge/save path.

    Organisation fields already use the same keys as company records.
    The vault retains product fields and replaces supplied lists wholesale.
    Callers retain responsibility for the product write lock.

    `shared` is whether the job being resolved may write the shared half
    (M2, decision D3; see `enrich.may_write_shared_company`). False makes
    every write a no-op: creating a company raises
    `CompanyCreationDenied`, and teaching an identifier or a name variant
    to a company that already exists returns that company unchanged, so
    the posting still links to it and adds nothing to it. That is what
    lets a tester select a company without mutating it.

    Retirement is not part of that flag, because it is the same answer
    for everybody (M2 soft retire, `vault.is_retired`):

    * `list_organisations` leaves a retired company out, so no
      resolution ever produces a NEW link to one -- not the admin's,
      whose own intake would otherwise resurrect the record they just
      retired, and not a tester's, whose write `vault.linkable_company`
      would refuse anyway.
    * `load_organisation` still answers with one, because an existing
      link has to keep resolving: that grandfathered link is the reason
      the delete leaves a tombstone rather than removing the file.
    """

    def __init__(self, root, shared=True):
        self.root = root
        self.shared = shared

    def list_organisations(self):
        return [c for c in vault.list_companies(self.root) if not vault.is_retired(c)]

    def load_organisation(self, organisation_id):
        return vault.load_company(self.root, organisation_id)

    def save_organisation(self, updates, organisation_id=None):
        if not self.shared:
            if organisation_id is None:
                raise CompanyCreationDenied(
                    'Only the admin can create a company.')
            # A no-op that answers in the shape the caller expects: the
            # record as it stands, so the ladder links to it and learns
            # nothing onto it.
            return vault.load_company(self.root, organisation_id)
        return vault.save_company(self.root, updates, organisation_id)
