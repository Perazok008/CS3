import gradio as gr

def SettingsSidebar(personalities: list[str], default_personality: str="Teacher"):
    """Build the settings sidebar with collapsible sections."""
    with gr.Column(scale=0):

        local_toggle = gr.Checkbox(
            label="Use local model",
            value=False,
            elem_id="local-toggle",
        )

        with gr.Accordion("Personality", open=True):
            personality_dd = gr.Dropdown(
                choices=personalities,
                value=default_personality,
                label="Personality",
                info="Choose how the assistant behaves.",
                elem_id="personality-select",
            )

        with gr.Accordion("Memory", open=False):
            min_save_importance = gr.Slider(
                minimum=1,
                maximum=5,
                value=3,
                step=1,
                label="Min save importance",
                info="Only save new memory items at or above this level.",
            )
            
            min_recall_importance = gr.Slider(
                minimum=1,
                maximum=5,
                value=3,
                step=1,
                label="Min recall importance",
                info="Only send saved memories at or above this level to the model.",
            )

            recent_turns = gr.Slider(
                minimum=1,
                maximum=20,
                value=5,
                step=1,
                label="Recent turns",
                info="Number of recent conversation turns to send.",
            )

        with gr.Accordion("Model", open=False):
            max_tokens = gr.Slider(
                minimum=1,
                maximum=2048,
                value=512,
                step=1,
                label="Max new tokens",
            )
            temperature = gr.Slider(
                minimum=0.1,
                maximum=4.0,
                value=0.2,
                step=0.1,
                label="Temperature",
            )
            top_p = gr.Slider(
                minimum=0.1,
                maximum=1.0,
                value=0.9,
                step=0.05,
                label="Top-p",
            )

    return {
        "personality_dd": personality_dd,
        "local_toggle": local_toggle,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "top_p": top_p,
        "min_recall_importance": min_recall_importance,
        "min_save_importance": min_save_importance,
        "recent_turns": recent_turns,
    }
