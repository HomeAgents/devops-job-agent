import logging

import azure.functions as func

from orchestrator.wake_poll import run_wake_cycle

app = func.FunctionApp()


@app.timer_trigger(
    schedule="0 */2 * * * *",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def email_wake(timer: func.TimerRequest) -> None:
    result = run_wake_cycle()
    logging.info("email_wake: %s", result)
