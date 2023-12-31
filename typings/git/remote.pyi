"""
This type stub file was generated by pyright.
"""

from git.cmd import Git
from git.util import (
    CallableRemoteProgress,
    IterableList,
    IterableObj,
    LazyMixin,
    RemoteProgress,
)
from git.config import GitConfigParser, SectionConstraint
from git.refs import Reference, RemoteReference, SymbolicReference, TagReference
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    NoReturn,
    Optional,
    TYPE_CHECKING,
    Union,
    overload,
)
from git.types import Commit_ish, Literal, PathLike
from git.repo.base import Repo
from git.objects.submodule.base import UpdateProgress

if TYPE_CHECKING: ...
flagKeyLiteral = Literal[" ", "!", "+", "-", "*", "=", "t", "?"]
log = ...
__all__ = ("RemoteProgress", "PushInfo", "FetchInfo", "Remote")

def add_progress(
    kwargs: Any,
    git: Git,
    progress: Union[
        RemoteProgress, UpdateProgress, Callable[..., RemoteProgress], None
    ],
) -> Any:
    """Add the --progress flag to the given kwargs dict if supported by the
    git command. If the actual progress in the given progress instance is not
    given, we do not request any progress
    :return: possibly altered kwargs"""
    ...

@overload
def to_progress_instance(progress: None) -> RemoteProgress: ...
@overload
def to_progress_instance(progress: Callable[..., Any]) -> CallableRemoteProgress: ...
@overload
def to_progress_instance(progress: RemoteProgress) -> RemoteProgress: ...
def to_progress_instance(
    progress: Union[Callable[..., Any], RemoteProgress, None]
) -> Union[RemoteProgress, CallableRemoteProgress]:
    """Given the 'progress' return a suitable object derived from
    RemoteProgress().
    """
    ...

class PushInfo(IterableObj):
    """
    Carries information about the result of a push operation of a single head::

        info = remote.push()[0]
        info.flags          # bitflags providing more information about the result
        info.local_ref      # Reference pointing to the local reference that was pushed
                            # It is None if the ref was deleted.
        info.remote_ref_string # path to the remote reference located on the remote side
        info.remote_ref # Remote Reference on the local side corresponding to
                        # the remote_ref_string. It can be a TagReference as well.
        info.old_commit # commit at which the remote_ref was standing before we pushed
                        # it to local_ref.commit. Will be None if an error was indicated
        info.summary    # summary line providing human readable english text about the push
    """

    __slots__ = ...
    _id_attribute_ = ...
    _flag_map = ...
    def __init__(
        self,
        flags: int,
        local_ref: Union[SymbolicReference, None],
        remote_ref_string: str,
        remote: Remote,
        old_commit: Optional[str] = ...,
        summary: str = ...,
    ) -> None:
        """Initialize a new instance
        local_ref: HEAD | Head | RemoteReference | TagReference | Reference | SymbolicReference | None
        """
        ...
    @property
    def old_commit(self) -> Union[str, SymbolicReference, Commit_ish, None]: ...
    @property
    def remote_ref(self) -> Union[RemoteReference, TagReference]:
        """
        :return:
            Remote Reference or TagReference in the local repository corresponding
            to the remote_ref_string kept in this instance."""
        ...
    @classmethod
    def iter_items(cls, repo: Repo, *args: Any, **kwargs: Any) -> NoReturn: ...

class PushInfoList(IterableList[PushInfo]):
    """
    IterableList of PushInfo objects.
    """

    def __new__(cls) -> PushInfoList: ...
    def __init__(self) -> None: ...
    def raise_if_error(self) -> None:
        """
        Raise an exception if any ref failed to push.
        """
        ...

class FetchInfo(IterableObj):
    """
    Carries information about the results of a fetch operation of a single head::

     info = remote.fetch()[0]
     info.ref           # Symbolic Reference or RemoteReference to the changed
                        # remote head or FETCH_HEAD
     info.flags         # additional flags to be & with enumeration members,
                        # i.e. info.flags & info.REJECTED
                        # is 0 if ref is SymbolicReference
     info.note          # additional notes given by git-fetch intended for the user
     info.old_commit    # if info.flags & info.FORCED_UPDATE|info.FAST_FORWARD,
                        # field is set to the previous location of ref, otherwise None
     info.remote_ref_path # The path from which we fetched on the remote. It's the remote's version of our info.ref
    """

    __slots__ = ...
    _id_attribute_ = ...
    _re_fetch_result = ...
    _flag_map: Dict[flagKeyLiteral, int] = ...
    @classmethod
    def refresh(cls) -> Literal[True]:
        """This gets called by the refresh function (see the top level
        __init__).
        """
        ...
    def __init__(
        self,
        ref: SymbolicReference,
        flags: int,
        note: str = ...,
        old_commit: Union[Commit_ish, None] = ...,
        remote_ref_path: Optional[PathLike] = ...,
    ) -> None:
        """
        Initialize a new instance
        """
        ...
    def __str__(self) -> str: ...
    @property
    def name(self) -> str:
        """:return: Name of our remote ref"""
        ...
    @property
    def commit(self) -> Commit_ish:
        """:return: Commit of our remote ref"""
        ...
    @classmethod
    def iter_items(cls, repo: Repo, *args: Any, **kwargs: Any) -> NoReturn: ...

class Remote(LazyMixin, IterableObj):
    """Provides easy read and write access to a git remote.

    Everything not part of this interface is considered an option for the current
    remote, allowing constructs like remote.pushurl to query the pushurl.

    NOTE: When querying configuration, the configuration accessor will be cached
    to speed up subsequent accesses."""

    __slots__ = ...
    _id_attribute_ = ...
    unsafe_git_fetch_options = ...
    unsafe_git_pull_options = ...
    unsafe_git_push_options = ...
    def __init__(self, repo: Repo, name: str) -> None:
        """Initialize a remote instance

        :param repo: The repository we are a remote of
        :param name: the name of the remote, i.e. 'origin'"""
        ...
    def __getattr__(self, attr: str) -> Any:
        """Allows to call this instance like
        remote.special( \\*args, \\*\\*kwargs) to call git-remote special self.name"""
        ...
    def __str__(self) -> str: ...
    def __repr__(self) -> str: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def exists(self) -> bool:
        """
        :return: True if this is a valid, existing remote.
            Valid remotes have an entry in the repository's configuration"""
        ...
    @classmethod
    def iter_items(cls, repo: Repo, *args: Any, **kwargs: Any) -> Iterator[Remote]:
        """:return: Iterator yielding Remote objects of the given repository"""
        ...
    def set_url(
        self,
        new_url: str,
        old_url: Optional[str] = ...,
        allow_unsafe_protocols: bool = ...,
        **kwargs: Any
    ) -> Remote:
        """Configure URLs on current remote (cf command git remote set_url)

        This command manages URLs on the remote.

        :param new_url: string being the URL to add as an extra remote URL
        :param old_url: when set, replaces this URL with new_url for the remote
        :param allow_unsafe_protocols: Allow unsafe protocols to be used, like ext
        :return: self
        """
        ...
    def add_url(
        self, url: str, allow_unsafe_protocols: bool = ..., **kwargs: Any
    ) -> Remote:
        """Adds a new url on current remote (special case of git remote set_url)

        This command adds new URLs to a given remote, making it possible to have
        multiple URLs for a single remote.

        :param url: string being the URL to add as an extra remote URL
        :param allow_unsafe_protocols: Allow unsafe protocols to be used, like ext
        :return: self
        """
        ...
    def delete_url(self, url: str, **kwargs: Any) -> Remote:
        """Deletes a new url on current remote (special case of git remote set_url)

        This command deletes new URLs to a given remote, making it possible to have
        multiple URLs for a single remote.

        :param url: string being the URL to delete from the remote
        :return: self
        """
        ...
    @property
    def urls(self) -> Iterator[str]:
        """:return: Iterator yielding all configured URL targets on a remote as strings"""
        ...
    @property
    def refs(self) -> IterableList[RemoteReference]:
        """
        :return:
            IterableList of RemoteReference objects. It is prefixed, allowing
            you to omit the remote path portion, i.e.::
            remote.refs.master # yields RemoteReference('/refs/remotes/origin/master')
        """
        ...
    @property
    def stale_refs(self) -> IterableList[Reference]:
        """
        :return:
            IterableList RemoteReference objects that do not have a corresponding
            head in the remote reference anymore as they have been deleted on the
            remote side, but are still available locally.

            The IterableList is prefixed, hence the 'origin' must be omitted. See
            'refs' property for an example.

            To make things more complicated, it can be possible for the list to include
            other kinds of references, for example, tag references, if these are stale
            as well. This is a fix for the issue described here:
            https://github.com/gitpython-developers/GitPython/issues/260
        """
        ...
    @classmethod
    def create(
        cls,
        repo: Repo,
        name: str,
        url: str,
        allow_unsafe_protocols: bool = ...,
        **kwargs: Any
    ) -> Remote:
        """Create a new remote to the given repository

        :param repo: Repository instance that is to receive the new remote
        :param name: Desired name of the remote
        :param url: URL which corresponds to the remote's name
        :param allow_unsafe_protocols: Allow unsafe protocols to be used, like ext
        :param kwargs: Additional arguments to be passed to the git-remote add command
        :return: New Remote instance
        :raise GitCommandError: in case an origin with that name already exists"""
        ...
    @classmethod
    def add(cls, repo: Repo, name: str, url: str, **kwargs: Any) -> Remote: ...
    @classmethod
    def remove(cls, repo: Repo, name: str) -> str:
        """Remove the remote with the given name

        :return: the passed remote name to remove
        """
        ...
    rm = ...
    def rename(self, new_name: str) -> Remote:
        """Rename self to the given new_name

        :return: self"""
        ...
    def update(self, **kwargs: Any) -> Remote:
        """Fetch all changes for this remote, including new branches which will
        be forced in ( in case your local remote branch is not part the new remote branches
        ancestry anymore ).

        :param kwargs:
            Additional arguments passed to git-remote update

        :return: self"""
        ...
    def fetch(
        self,
        refspec: Union[str, List[str], None] = ...,
        progress: Union[RemoteProgress, None, UpdateProgress] = ...,
        verbose: bool = ...,
        kill_after_timeout: Union[None, float] = ...,
        allow_unsafe_protocols: bool = ...,
        allow_unsafe_options: bool = ...,
        **kwargs: Any
    ) -> IterableList[FetchInfo]:
        """Fetch the latest changes for this remote

        :param refspec:
            A "refspec" is used by fetch and push to describe the mapping
            between remote ref and local ref. They are combined with a colon in
            the format <src>:<dst>, preceded by an optional plus sign, +.
            For example: git fetch $URL refs/heads/master:refs/heads/origin means
            "grab the master branch head from the $URL and store it as my origin
            branch head". And git push $URL refs/heads/master:refs/heads/to-upstream
            means "publish my master branch head as to-upstream branch at $URL".
            See also git-push(1).

            Taken from the git manual

            Fetch supports multiple refspecs (as the
            underlying git-fetch does) - supplying a list rather than a string
            for 'refspec' will make use of this facility.
        :param progress: See 'push' method
        :param verbose: Boolean for verbose output
        :param kill_after_timeout:
            To specify a timeout in seconds for the git command, after which the process
            should be killed. It is set to None by default.
        :param allow_unsafe_protocols: Allow unsafe protocols to be used, like ext
        :param allow_unsafe_options: Allow unsafe options to be used, like --upload-pack
        :param kwargs: Additional arguments to be passed to git-fetch
        :return:
            IterableList(FetchInfo, ...) list of FetchInfo instances providing detailed
            information about the fetch results

        :note:
            As fetch does not provide progress information to non-ttys, we cannot make
            it available here unfortunately as in the 'push' method."""
        ...
    def pull(
        self,
        refspec: Union[str, List[str], None] = ...,
        progress: Union[RemoteProgress, UpdateProgress, None] = ...,
        kill_after_timeout: Union[None, float] = ...,
        allow_unsafe_protocols: bool = ...,
        allow_unsafe_options: bool = ...,
        **kwargs: Any
    ) -> IterableList[FetchInfo]:
        """Pull changes from the given branch, being the same as a fetch followed
        by a merge of branch with your local branch.

        :param refspec: see :meth:`fetch` method
        :param progress: see :meth:`push` method
        :param kill_after_timeout: see :meth:`fetch` method
        :param allow_unsafe_protocols: Allow unsafe protocols to be used, like ext
        :param allow_unsafe_options: Allow unsafe options to be used, like --upload-pack
        :param kwargs: Additional arguments to be passed to git-pull
        :return: Please see :meth:`fetch` method"""
        ...
    def push(
        self,
        refspec: Union[str, List[str], None] = ...,
        progress: Union[
            RemoteProgress, UpdateProgress, Callable[..., RemoteProgress], None
        ] = ...,
        kill_after_timeout: Union[None, float] = ...,
        allow_unsafe_protocols: bool = ...,
        allow_unsafe_options: bool = ...,
        **kwargs: Any
    ) -> PushInfoList:
        """Push changes from source branch in refspec to target branch in refspec.

        :param refspec: see 'fetch' method
        :param progress:
            Can take one of many value types:

            * None to discard progress information
            * A function (callable) that is called with the progress information.
              Signature: ``progress(op_code, cur_count, max_count=None, message='')``.
              `Click here <http://goo.gl/NPa7st>`__ for a description of all arguments
              given to the function.
            * An instance of a class derived from ``git.RemoteProgress`` that
              overrides the ``update()`` function.

        :note: No further progress information is returned after push returns.
        :param kill_after_timeout:
            To specify a timeout in seconds for the git command, after which the process
            should be killed. It is set to None by default.
        :param allow_unsafe_protocols: Allow unsafe protocols to be used, like ext
        :param allow_unsafe_options: Allow unsafe options to be used, like --receive-pack
        :param kwargs: Additional arguments to be passed to git-push
        :return:
            A ``PushInfoList`` object, where each list member
            represents an individual head which had been updated on the remote side.
            If the push contains rejected heads, these will have the PushInfo.ERROR bit set
            in their flags.
            If the operation fails completely, the length of the returned PushInfoList will
            be 0.
            Call ``.raise_if_error()`` on the returned object to raise on any failure.
        """
        ...
    @property
    def config_reader(self) -> SectionConstraint[GitConfigParser]:
        """
        :return:
            GitConfigParser compatible object able to read options for only our remote.
            Hence you may simple type config.get("pushurl") to obtain the information"""
        ...
    @property
    def config_writer(self) -> SectionConstraint:
        """
        :return: GitConfigParser compatible object able to write options for this remote.
        :note:
            You can only own one writer at a time - delete it to release the
            configuration file and make it usable by others.

            To assure consistent results, you should only query options through the
            writer. Once you are done writing, you are free to use the config reader
            once again."""
        ...
