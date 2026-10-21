# TODO: implement a use case to re-index books that's already been indexed.
# this should be wired to the confirm action of the dialog displayed when
# trying to edit embedding model or provider on the settings screen.
# should changing chunk size also trigger this action?
# why not make it so there is a re-index button either in the cards displayed in
# the library or the chat screen. that way the user controls when to re-index.
# as long as the chat features continues to work even after embedding settings
# have changed, there can be books embedded with different settings.
# if this is the case, then the flow in the settings screen might need to change as
# well.


class ReindexDocument:
    def __init__(self) -> None:
        pass

    async def __call__(self) -> None:
        raise NotImplementedError
