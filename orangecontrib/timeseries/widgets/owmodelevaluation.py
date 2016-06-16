from collections import OrderedDict

import numpy as np

from PyQt4.QtCore import QSize

from Orange.widgets import widget, gui, settings
from Orange.widgets.utils.itemmodels import PyTableModel

from orangecontrib.timeseries import Timeseries, rmse, mae, mape, pocid, r2
from orangecontrib.timeseries.models import _BaseModel


class Output:
    TIMESERIES = 'Time series'


class OWModelEvaluation(widget.OWWidget):
    name = 'Model Evaluation'
    description = '''Evaluate different time series' models by comparing the
                  errors they make in terms of:
                  root mean squared error (RMSE),
                  median absolute error (MAE),
                  mean absolute percent error (MAPE),
                  prediction of change in direction (POCID),
                  coefficient of determination (R²),
                  Akaike information criterion (AIC), and
                  Bayesian information criterion (BIC).
                  '''
    icon = 'icons/ModelEvaluation.svg'
    priority = 300

    inputs = [("Time series", Timeseries, 'set_data'),
              ("Time series model", _BaseModel, 'set_model', widget.Multiple)]

    n_folds = settings.Setting(20)
    forecast_steps = settings.Setting(3)
    autocommit = settings.Setting(False)

    def __init__(self):
        self.data = None
        self._models = OrderedDict()
        box = gui.vBox(self.controlArea, 'Evaluation Parameters')
        gui.spin(box, self, 'n_folds', 1, 100,
                 label='Number of folds:',
                 callback=self.on_changed)
        gui.spin(box, self, 'forecast_steps', 1, 100,
                 label='Forecast steps:',
                 callback=self.on_changed)
        gui.auto_commit(box, self, 'autocommit', '&Apply')
        gui.rubber(self.controlArea)

        self.model = model = PyTableModel(parent=self)
        model.setHorizontalHeaderLabels(['RMSE', 'MAE', 'MAPE', 'POCID', 'R²', 'AIC', 'BIC'])
        view = gui.TableView(self)
        view.setModel(model)
        view.horizontalHeader().setStretchLastSection(False)
        view.verticalHeader().setVisible(True)
        self.mainArea.layout().addWidget(view)

    def sizeHint(self):
        return QSize(650, 175)

    def set_data(self, data):
        self.data = data
        self.on_changed()

    def set_model(self, model, id):
        if model is None:
            self._models.pop(id, None)
        else:
            self._models[id] = model.copy()
        self.on_changed()

    def on_changed(self):
        self.commit()

    def commit(self):
        self.error()
        self.model.clear()
        data = self.data
        if not data or not self._models:
            return
        if not data.domain.class_var:
            self.error('Data requires a target variable. Use Select Columns '
                       'widget to set one variable as target.')
            return

        n_folds = self.n_folds
        forecast_steps = self.forecast_steps

        max_lag = max(m.max_order for m in self._models.values())
        if n_folds * forecast_steps + max_lag > len(data):
            self.error('Supplied time series is too short for this many folds '
                       '/ step size. Retry with fewer iterations.')
            return

        def _score_vector(model, true, pred):
            true = np.asanyarray(true)
            pred = np.asanyarray(pred)
            nonnan = ~np.isnan(true)
            if not nonnan.all():
                pred = pred[nonnan]
                true = true[nonnan]
            if pred.size:
                row = [score(true, pred) for score in (rmse, mae, mape, pocid, r2)]
            else:
                row = ['err'] * 5
            try:
                row.extend([model.results.aic, model.results.bic])
            except Exception:
                row.extend(['err'] * 2)
            return row

        res = []
        vheaders = []
        interp_data = data.interp()
        true_y = np.ravel(data[:, data.domain.class_var])
        with self.progressBar(len(self._models) * (n_folds + 1) + 1) as progress:
            for model in self._models.values():
                model_name = str(getattr(model, 'name', model))
                vheaders.append(model_name)
                full_true = []
                full_pred = []
                for fold in range(1, n_folds + 1):
                    train_end = -fold * forecast_steps
                    try:
                        model.fit(interp_data[:train_end])
                        pred, _, _ = model.predict(forecast_steps)
                    except Exception:
                        continue
                    finally:
                        progress.advance()

                    full_true.extend(true_y[train_end:][:forecast_steps])  # Sliced twice because it doesn't work at the end, e.g. [-3:0] == [] :(
                    full_pred.extend(np.c_[pred][:, 0])  # Only interested in the class var
                    assert len(full_true) == len(full_pred)

                res.append(_score_vector(model, full_true, full_pred))

                vheaders.append(model_name + ' (in-sample)')
                try:
                    model.fit(interp_data)
                    fittedvalues = model.fittedvalues()
                    if fittedvalues.ndim > 1:
                        fittedvalues = fittedvalues[..., 0]
                except Exception:
                    row = ['err'] * 7
                else:
                    row = _score_vector(model, true_y, fittedvalues)
                res.append(row)

        self.model.setVerticalHeaderLabels(vheaders)
        self.model.wrap(res)


if __name__ == "__main__":
    from PyQt4.QtGui import QApplication
    from Orange.data import Domain
    from orangecontrib.timeseries import ARIMA, VAR

    a = QApplication([])
    ow = OWModelEvaluation()

    data = Timeseries('yahoo_MSFT')
    # Make Adjusted Close a class variable
    attrs = [var.name for var in data.domain.attributes]
    if 'Adj Close' in attrs:
        attrs.remove('Adj Close')
        data = Timeseries(Domain(attrs, [data.domain['Adj Close']], None, source=data.domain), data)

    ow.set_data(data)
    ow.set_model(ARIMA((1, 1, 1)), 1)
    ow.set_model(ARIMA((2, 1, 0)), 2)
    # ow.set_model(ARIMA((0, 1, 1)), 3)
    # ow.set_model(ARIMA((4, 1, 0)), 4)
    ow.set_model(VAR(1), 11)
    ow.set_model(VAR(5), 12)
    # ow.set_model(VAR(6), 14)

    ow.show()
    a.exec()