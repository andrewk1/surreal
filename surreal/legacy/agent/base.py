"""
A template class that defines base agent APIs
"""
import surreal.utils as U
from surreal.session import (
    Loggerplex, AgentTensorplex, EvalTensorplex,
    PeriodicTracker, PeriodicTensorplex, extend_config,
    BASE_ENV_CONFIG, BASE_SESSION_CONFIG, BASE_LEARN_CONFIG
)
from surreal.distributed import RedisClient, ParameterServer


class AgentMode(U.StringEnum):
    training = ()
    eval_stochastic = ()
    eval_deterministic = ()


class Agent(metaclass=U.AutoInitializeMeta):
    def __init__(self,
                 learner_config,
                 env_config,
                 session_config,
                 agent_id,
                 agent_mode):
        """
        Write all logs to self.log
        """
        self.learner_config = extend_config(learner_config, self.default_config())
        self.env_config = extend_config(env_config, BASE_ENV_CONFIG)
        self.session_config = extend_config(session_config, BASE_SESSION_CONFIG)
        self.agent_mode = AgentMode[agent_mode]
        if self.agent_mode == AgentMode.training:
            U.assert_type(agent_id, int)
            logger_name = 'agent-{}'.format(agent_id)
            self.tensorplex = AgentTensorplex(
                agent_id=agent_id,
                session_config=self.session_config
            )
        else:
            logger_name = 'eval-{}'.format(agent_id)
            self.tensorplex = EvalTensorplex(
                eval_id=str(agent_id),
                session_config=self.session_config
            )
        self._periodic_tensorplex = PeriodicTensorplex(
            tensorplex=self.tensorplex,
            period=self.session_config.tensorplex.update_schedule.agent,
            is_average=True,
            keep_full_history=False
        )

        self._client = RedisClient(
            host=self.session_config.ps.host,
            port=self.session_config.ps.port
        )
        self.log = Loggerplex(
            name=logger_name,
            session_config=self.session_config
        )

    def _initialize(self):
        """
        Implements AutoInitializeMeta meta class.
        distributed.ps.TorchListener deprecated in favor of active pulling

        from surreal.distributed.ps.torch_listener import TorchListener
        self._listener = TorchListener(
            redis_client=self._client,
            module_dict=self.module_dict()
        )
        self._listener.run_listener_thread()
        """
        self._parameter_server = ParameterServer(
            redis_client=self._client,
            module_dict=self.module_dict(),
            name=self.session_config.ps.name
        )

    def act(self, obs):
        """
        Abstract method for taking actions.
        You should check `self.agent_mode` in the function and change act()
        logic with respect to training VS evaluation.

        Args:
            obs: typically a single obs, make sure to vectorize it first before
                passing to the torch `model`.

        Returns:
            action to be executed in the env
        """
        raise NotImplementedError

    def module_dict(self):
        """
        Returns:
            a dict of name -> surreal.utils.pytorch.Module
        """
        raise NotImplementedError

    def pull_parameters(self):
        """
        Update agent by pulling parameters from parameter server.
        """
        return self._parameter_server.pull()

    def pull_parameter_info(self):
        """
        Update agent by pulling parameters from parameter server.
        """
        return self._parameter_server.pull_info()

    def update_tensorplex(self, tag_value_dict, global_step=None):
        self._periodic_tensorplex.update(tag_value_dict, global_step)

    def default_config(self):
        """
        Returns:
            a dict of defaults.
        """
        return BASE_LEARN_CONFIG

    def close(self):
        """
        Clean up after the agent exits.
        """
        pass

    def set_agent_mode(self, agent_mode):
        """
        Args:
            agent_mode: enum of AgentMode class
        """
        self.agent_mode = AgentMode[agent_mode]

    def __del__(self):
        self.close()