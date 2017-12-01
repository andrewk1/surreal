import sys
import weakref
import surreal.utils as U
import threading
from collections import namedtuple
from .zmq_struct import ZmqQueue


ExpTuple = namedtuple('ExpTuple', 'obs action reward done info')


class ExpQueue(object):
    def __init__(self,
                 port,
                 max_size,
                 exp_handler):
        assert callable(exp_handler)
        self.max_size = max_size
        self._queue = ZmqQueue(
            port=port,
            max_size=max_size,
            start_thread=False,
            is_pyobj=True
        )
        self._dequeue_thread = None
        # ob_hash: weakref(ob)  for de-duplicating
        # when the last strong ref disappears, the ob will also be deleted here
        self._weakref_map = weakref.WeakValueDictionary()
        self._exp_handler = exp_handler

    def start_enqueue_thread(self):
        self._queue.start_enqueue_thread()

    def _dequeue_loop(self):  # blocking
        while True:
            exp_tuples, ob_storage = self._queue.get()
            exp_tuple, ob_list = None, None
            for exp_tuple in exp_tuples:
                # deflate exp_tuple
                ob_list = exp_tuple[0]
                U.assert_type(ob_list, list)
                for i, ob_hash in enumerate(ob_list):
                    if ob_hash in self._weakref_map:
                        ob_list[i] = self._weakref_map[ob_hash]
                    else:
                        ob_list[i] = ob_storage[ob_hash]
                        self._weakref_map[ob_hash] = ob_list[i]
                self._exp_handler(ExpTuple(*exp_tuple))
            # clean up ref counts
            del exp_tuples, ob_storage, exp_tuple, ob_list

    def start_dequeue_thread(self):
        """
        handler function takes an experience tuple
        ([obs], action, reward, done, info)
        inserts it into a priority replay data structure.
        """
        if self._dequeue_thread is not None:
            raise ValueError('Dequeue thread is already running')
        self._dequeue_thread = U.start_thread(self._dequeue_loop)
        return self._dequeue_thread

    def size(self):
        return len(self._queue)

    __len__ = size

    def occupancy(self):
        "ratio of current size / max size"
        return 1. * self.size() / self.max_size

    def weakref_keys(self):
        return list(self._weakref_map.keys())

    def weakref_size(self):
        return len(self._weakref_map)

    def weakref_counts(self):
        return {key: sys.getrefcount(value) - 3  # counting itself incrs ref
                for key, value in self._weakref_map.items()}
