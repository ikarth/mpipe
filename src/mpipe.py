"""MPipe is a multiprocessing pipeline software framework in Python."""

import multiprocessing

class TubeP:
    """A unidirectional communication channel 
    using :class:`multiprocessing.Connection` for underlying implementation."""

    def __init__(self):
        (self._conn1, 
         self._conn2) = multiprocessing.Pipe(duplex=False)

    def put(self, data):
        """Put an item on the tube."""
        self._conn2.send(data)

    def get(self, timeout=None):
        """Return the next available item from the tube.

        Blocks if tube is empty, until a producer for the tube puts an item on it."""
        if timeout:
            # Todo: Consider locking the poll/recv block.
            # Otherwise, this method is not thread safe.
            if self._conn1.poll(timeout):
                return (True, self._conn1.recv())
            else:
                return (False, None)
        return self._conn1.recv()

class TubeQ:
    """A unidirectional communication channel 
    using :class:`multiprocessing.Queue` for underlying implementation."""

    def __init__(self):
        self._queue = multiprocessing.Queue()

    def put(self, data):
        """Put an item on the tube."""
        self._queue.put(data)

    def get(self, timeout=None):
        """Return the next available item from the tube.

        Blocks if tube is empty, until a producer for the tube puts an item on it."""
        if timeout:
            try:
                result = self._queue.get(True, timeout)
            except multiprocessing.Queue.Empty:
                return(False, None)
            return(True, result)
        return self._queue.get()


class OrderedWorker(multiprocessing.Process):
    """An OrderedWorker object operates in a stage where the order 
    of output results always matches that of corresponding input tasks.

    A worker is linked to its two nearest neighbors -- the previous 
    worker and the next -- all workers in the stage thusly linked 
    in circular fashion. 
    Input tasks are fetched in this order, and before publishing it's result, 
    a worker first waits for it's previous neighbor to do the same."""

    def __init__(self):
        pass

    def init2(
        self, 
        input_tube,    # Read task from the input tube.
        output_tubes,  # Send result on all the output tubes.
        num_workers,   # Total number of workers in the stage.
        ):
        """Create a worker with *input_tube* and an iterable of *output_tubes*.
        The worker reads a task from *input_tube* and writes the result to *output_tubes*."""
        super(OrderedWorker, self).__init__()
        self._tube_task_input = input_tube
        self._tubes_result_output = output_tubes
        self._num_workers = num_workers

        # Serializes reading from input tube.
        self._lock_prev_input = None
        self._lock_next_input = None

        # Serializes writing to output tube.
        self._lock_prev_output = None
        self._lock_next_output = None

    @staticmethod
    def getTubeClass():
        """Return the tube class implementation."""
        return TubeP

    @classmethod
    def assemble(cls, input_tube, output_tubes, size):
        """Create, assemble and start workers."""

        # Create the workers.
        workers = []
        for ii in range(size):
            worker = cls()
            worker.init2(
                input_tube,
                output_tubes,
                size,
                )
            workers.append(worker)

        # Connect the workers.
        for ii in range(size):
            worker_this = workers[ii]
            worker_prev = workers[ii-1]
            worker_prev._link(
                worker_this, 
                next_is_first=(ii==0),  # Designate 0th worker as the first.
                )

        # Start the workers.
        for worker in workers:
            worker.start()

    def _link(self, next_worker, next_is_first=False):
        """Link the worker to the given next worker object, 
        connecting the two workers with communication tubes."""

        lock = multiprocessing.Lock()
        next_worker._lock_prev_input = lock
        self._lock_next_input = lock
        lock.acquire()

        lock = multiprocessing.Lock()
        next_worker._lock_prev_output = lock
        self._lock_next_output = lock
        lock.acquire()

        # If the next worker is the first one, trigger it now.
        if next_is_first:
            self._lock_next_input.release()
            self._lock_next_output.release()

    def putResult(self, result, count=0):
        """Register the *result* by putting it on all the output tubes."""
        self._lock_prev_output.acquire()
        for tube in self._tubes_result_output:
            tube.put((result, count))
        self._lock_next_output.release()
        
    def run(self):
        while True:
            try:
                # Wait on permission from the previous worker that it's 
                # okay to retrieve the input task.
                self._lock_prev_input.acquire()

                # Retrieve the input task.
                (task, count) = self._tube_task_input.get()

                # Give permission to the next worker that it's 
                # okay to retrieve the input task.
                self._lock_next_input.release()

            except:
                (task, count) = (None, 0)

            # In case the task is None, it represents the "stop" request,
            # the count being the number of workers in this stage that had
            # already stopped.
            if task is None:

                # If this worker is the last one (of its stage) to receive the 
                # "stop" request, propagate "stop" to the next stage. Otherwise,
                # maintain the "stop" signal in this stage for another worker that
                # will pick it up. 
                count += 1
                if count == self._num_workers:
                    
                    # Propagating the "stop" to the next stage does not require
                    # synchronization with previous and next worker because we're
                    # guaranteed (from the count value) that this is the last worker alive. 
                    # Therefore, just put the "stop" signal on the result tube.
                    for tube in self._tubes_result_output:
                        tube.put((None, 0))

                else:
                    self._tube_task_input.put((None, count))

                # Honor the "stop" request by exiting the process.
                break  

            # The task is not None, meaning that it's an actual task to
            # be processed. Therefore let's call doTask().
            result = self.doTask(task)

            # If doTask() actually returns a result (and the result is not None),
            # it indicates that it did not call putResult(), instead intending
            # it to be called now.
            if result is not None:
                self.putResult(result)

    def doTask(self, task):
        """Implement this function in the subclass.
        The implementation can publish the output result in one of two ways: 
        1) either by calling :meth:`putResult` and returning ``None`` or
        2) by returning the result (other than ``None``.)"""
        return True


class UnorderedWorker(multiprocessing.Process):
    """An UnorderedWorker object operates independently of other
    workers in the stage, publishing it's result without coordinating
    with others. The order of output results may not match 
    that of corresponding input tasks."""

    def __init__(self):
        pass

    def init2(
        self, 
        input_tube,    # Read task from the input tube.
        output_tubes,  # Send result on all the output tubes.
        num_workers,   # Total number of workers in the stage.
        ):
        """Create a worker with *input_tube* and an iterable of *output_tubes*.
        The worker reads a task from *input_tube* and writes the result to *output_tubes*."""
        super(UnorderedWorker, self).__init__()
        self._tube_task_input = input_tube
        self._tubes_result_output = output_tubes
        self._num_workers = num_workers

    @staticmethod
    def getTubeClass():
        """Return the tube class implementation."""
        return TubeQ
    
    @classmethod
    def assemble(cls, input_tube, output_tubes, size):
        """Create, assemble and start workers."""

        # Create the workers.
        workers = []
        for ii in range(size):
            worker = cls()
            worker.init2(
                input_tube,
                output_tubes,
                size,
                )
            workers.append(worker)

        # Start the workers.
        for worker in workers:
            worker.start()

    def putResult(self, result, count=0):
        """Register the *result* by putting it on all the output tubes."""
        for tube in self._tubes_result_output:
            tube.put((result, count))

    def run(self):
        while True:
            try:
                (task, count) = self._tube_task_input.get()
            except:
                (task, count) = (None, 0)

            # In case the task is None, it represents the "stop" request,
            # the count being the number of workers in this stage that had
            # already stopped.
            if task is None:

                # If this worker is the last one (of its stage) to receive the 
                # "stop" request, propagate "stop" to the next stage. Otherwise,
                # maintain the "stop" signal in this stage for another worker that
                # will pick it up. 
                count += 1
                if count == self._num_workers:
                    self.putResult(None)
                else:
                    self._tube_task_input.put((None, count))

                # Honor the "stop" request by exiting the process.
                break  

            # The task is not None, meaning that it's an actual task to
            # be processed. Therefore let's call doTask().
            result = self.doTask(task)

            # If doTask() actually returns a result (and the result is not None),
            # it indicates that it did not call putResult(), instead intending
            # it to be called now.
            if result is not None:
                self.putResult(result)

    def doTask(self, task):
        """Implement this function in the subclass.
        The implementation can publish the output result in one of two ways: 
        1) either by calling :meth:`putResult` and returning ``None`` or
        2) by returning the result (other than ``None``.)"""
        return True


class Stage(object):
    """The Stage is an assembly of workers of identical functionality."""

    def __init__(self, worker_class, size=1):
        """Create a stage of workers of given *worker_class* implementation, 
        with *size* indicating the number of workers within the stage."""
        self._worker_class = worker_class
        self._size = size
        self._input_tube = self._worker_class.getTubeClass()()
        self._output_tubes = list()
        self._next_stages = list()

    def put(self, task):
        """Put *task* on the stage's input tube."""
        self._input_tube.put((task,0))

    def get(self, timeout=None):
        """Retrieve results from all the output tubes."""
        valid = False
        result = None
        for tube in self._output_tubes:
            if timeout:
                valid, result = tube.get(timeout)
                if valid:
                    result = result[0]
            else:
                result = tube.get()[0]
        if timeout:
            return valid, result
        return result

    def link(self, next_stage):
        """Link to the given downstream stage object
        by adding it's input tube to the list of this stage's output tubes."""
        self._output_tubes.append(next_stage._input_tube)
        self._next_stages.append(next_stage)

    def getLeaves(self):
        """Return the downstream leaf stages of this stage."""
        result = list()
        if not self._next_stages:
            result.append(self)
        else:
            for stage in self._next_stages:
                leaves = stage.getLeaves()
                result += leaves
        return result

    def build(self):
        """Create and start up the internal workers."""

        # If there's no output tube, it means that this stage
        # is at the end of a fork (hasn't been linked to any stage downstream.)
        # Therefore, create one output tube.
        if not self._output_tubes:
            self._output_tubes.append(self._worker_class.getTubeClass()())

        self._worker_class.assemble(
            self._input_tube,
            self._output_tubes,
            self._size,
            )

        # Build all downstream stages.
        for stage in self._next_stages:
            stage.build()


class OrderedStage(Stage):
    """A specialized :class:`~mpipe.Stage`, 
    internally creating :class:`~mpipe.OrderedWorker` objects."""
    def __init__(self, target, size=1):
        """Constructor takes a function implementing 
        :meth:`OrderedWorker.doTask`."""
        class wclass(OrderedWorker):
            def doTask(self, task):
                return target(task)
        super(OrderedStage, self).__init__(wclass, size)


class UnorderedStage(Stage):
    """A specialized :class:`~mpipe.Stage`, 
    internally creating :class:`~mpipe.UnorderedWorker` objects."""
    def __init__(self, target, size=1):
        """Constructor takes a function implementing
        :meth:`UnorderedWorker.doTask`."""
        class wclass(UnorderedWorker):
            def doTask(self, task):
                return target(task)
        super(UnorderedStage, self).__init__(wclass, size)


class Pipeline(object):
    """A pipeline of stages."""
    def __init__(self, input_stage):
        """Constructor takes the root upstream stage."""
        self._input_stage = input_stage
        self._output_stages = input_stage.getLeaves()
        self._input_stage.build()

    def put(self, task):
        """Put *task* on the pipeline."""
        self._input_stage.put(task)

    def get(self, timeout=None):
        """Return result from the pipeline."""
        result = None
        for stage in self._output_stages:
            result = stage.get(timeout)
        return result

    def results(self):
        """Return a generator to iterate over results from the pipeline."""
        while True:
            result = self.get()
            if result is None: break
            yield result

# The end.