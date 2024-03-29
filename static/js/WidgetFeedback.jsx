// App.jsx
import React from "react";
import FabricHelpers from './FabricHelpers';

export default class WidgetFeedback extends React.Component {
  constructor(props) {
  	super(props);
    this.feedbackMessage = props.message; 
    this.updateConstraintsCanvas = props.updateConstraintsCanvas; 
    this.id = props.id; 
    this.parentShape = props.parentShape; 
    this.action = props.action; 
    
    this.state = {
      highlighted: props.highlighted
    }
  }

  static getDerivedStateFromProps(nextProps, prevState) {
    return {
      highlighted: nextProps.highlighted
    }    
  }

  render () {
    var self = this;
    var highlighted = this.state.highlighted; 
    return (
      <div className="widget-feedback-container">
        <div className="widget-feedback">
          <ul className={"widget-feedback-items " + (highlighted ? "highlighted" : "")}>
            <li className="widget-feedback-items-list"> 
              <span className="widget-feedback-items-label">
              {this.feedbackMessage}
              </span>
              <button className={"widget-feedback-items-remove " + (highlighted ? "highlighted" : "")} onClick={
                  function() { 
                    self.updateConstraintsCanvas(self.parentShape, self.action, "undo"); 
                  }}>
                <span className="glyphicon glyphicon-minus" aria-hidden="true"></span>
              </button>
            </li>
          </ul>
        </div>
      </div>); 
  }
}
