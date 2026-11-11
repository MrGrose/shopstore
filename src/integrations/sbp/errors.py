class SBPError(Exception):
    pass


class SBPAuthError(SBPError):
    pass


class SBPApiError(SBPError):
    pass


class SBPTimeoutError(SBPError):
    pass


class SBPPaymentReconciliationError(SBPError):
    pass
