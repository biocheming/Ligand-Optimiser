#!/usr/bin/env python

from .energy import FSim
from simtk import unit
from scipy.optimize import minimize
import copy

#CONSTANTS
e = unit.elementary_charges

class Optimize(object):
    def __init__(self, wt_ligand, complex_sys, solvent_sys, output_folder, num_frames, name, steps):

        self.complex_sys = complex_sys
        self.solvent_sys = solvent_sys
        self.num_frames = num_frames
        self.steps = steps
        self.output_folder = output_folder
        wt_parameters = [x[0]/e for x in wt_ligand.get_parameters()]
        self.net_charge = sum(wt_parameters)
        self.wt_parameters = [[x] for x in wt_parameters]
        Optimize.optimize(self, name)

    def optimize(self, name):
        """optimising ligand charges
        """
        if name == 'scipy':
            opt_charges, ddg = Optimize.scipy_opt(self)
            print(opt_charges)
        else:
            Optimize.grad_opt(self, name)


    def scipy_opt(self):
        cons = {'type': 'eq', 'fun': constraint, 'args': [self.net_charge]}
        charges = self.wt_parameters
        prev_charges = self.wt_parameters
        ddg = 0.0
        for step in range(self.steps):
            max_change = 0.5
            bnds = [sorted((x[0] - max_change * x[0], x[0] + max_change * x[0])) for x in prev_charges]
            sol = minimize(objective, charges, bounds=bnds, options={'maxiter': 1}, jac=gradient,
                           args=(prev_charges, self.complex_sys, self.solvent_sys, self.num_frames), constraints=cons)
            prev_charges = charges
            charges = [[x] for x in sol.x]
            print(sol)
            ddg += sol.fun
            print("Current binding free energy improvement {0} for step {1}/{2}".format(ddg, step+1, self.steps))
            if step != 0:
                #run new dynamics with updated charges
                self.complex_sys[1] = self.complex_sys[0].run_parallel_dynamics(self.output_folder, 'complex_step'+str(step),
                                                                                self.num_frames*2500, prev_charges)
                self.solvent_sys[1] = self.solvent_sys[0].run_parallel_dynamics(self.output_folder, 'solvent_step'+str(step),
                                                                                self.num_frames*2500, prev_charges)
        return sol.x, ddg

    def grad_opt(self, opt_type):
        """
        different strategries of gradient descent
        """
        # assert that opt_type is known
        assert opt_type in ['gradient_descent',
                            'adagrad',
                            'momentum']
        # import tensorflow locally here
        import tensorflow as tf
        # enable eager execution if it is not enabled in the background
        try:
            tf.enable_eager_execution()
        except:
            pass
        # a small learning rate helps keep the perturbation small
        learning_rate = 0.1
        # specify the optimizer based on the type
        if opt_type == 'gradient_descent':
            optimizer = tf.training.optimizer.GradientDescentOptimizer(learning_rate=learning_rate)
        elif opt_type == 'adagrad':
            optimizer = tf.training.optimizer.AdagradOptimizer(learning_rate=learning_rate)
        elif opt_type == 'momentum':
            optimizer = tf.trainig.optimizer.MomentumOptimizer(learning_rate=learning_rate)
        # code the weights as a variable
        wt_parameters = np.array(self.wt_parameters, dtype=np.float32)
        charge_sum = tf.reduce_sum(wt_parameters)
        wt_vat = tf.Variable(wt_parameters,
                            constraint=lambda x : charge_sum * tf.div(x, tf.norm(x)))
        for step in range(self.steps):
            # optimize
            opt_op = optimizer.minimize(lambda x: objective(x.numpy(),
                                        self.wt_energy_complex, self.wt_energy_solvent,
                                        self.complex_sys, self.solvent_sys, self.num_frames))
            opt_op.run()
            #run new dynamics with updated charges
            self.complex_sys[0].run_dynamics(self.output_folder, 'complex'+str(step), wt_parameters)
            self.solvent_sys[0].run_dynamics(self.output_folder, 'solvent'+str(step), wt_parameters)
            #update path to trajectrory
            self.complex_sys[1] = self.output_folder+'complex'+str(step)
            self.solvent_sys[1] = self.output_folder+'solvent'+str(step)
            #get new wt_mutant energies
            self.wt_energy_complex = FSim.get_mutant_energy(self.complex_sys[0], [self.wt_parameters],
                                                            self.complex_sys[1],
                                                            self.complex_sys[2], self.num_frames, True)
            self.wt_energy_solvent = FSim.get_mutant_energy(self.solvent_sys[0], [self.wt_parameters],
                                                            self.solvent_sys[1],
                                                            self.solvent_sys[2], self.num_frames, True)


def objective(mutant_parameters, wt_parameters, complex_sys, solvent_sys, num_frames):
    mutant_parameters = [[[x] for x in mutant_parameters]]
    print('Computing Objective...')
    complex_free_energy = FSim.treat_phase(complex_sys[0], wt_parameters, mutant_parameters,
                                           complex_sys[1], complex_sys[2], num_frames)
    solvent_free_energy = FSim.treat_phase(solvent_sys[0], wt_parameters, mutant_parameters,
                                           solvent_sys[1], solvent_sys[2], num_frames)
    binding_free_energy = complex_free_energy[0] - solvent_free_energy[0]
    return binding_free_energy


def gradient(mutant_parameters, wt_parameters, complex_sys, solvent_sys, num_frames):
    num_frames = int(num_frames/10)
    binding_free_energy = []
    og_mutant_parameters = mutant_parameters
    mutant_parameters = []
    for i in range(len(og_mutant_parameters)):
        mutant = copy.deepcopy(og_mutant_parameters)
        mutant[i] = mutant[i] + 1.5e-04
        mutant = [[x] for x in mutant]
        mutant_parameters.append(mutant)

    print('Computing Jacobian...')
    complex_free_energy = FSim.treat_phase(complex_sys[0], wt_parameters, mutant_parameters,
                                           complex_sys[1], complex_sys[2], num_frames)
    solvent_free_energy = FSim.treat_phase(solvent_sys[0], wt_parameters, mutant_parameters,
                                           solvent_sys[1], solvent_sys[2], num_frames)
    for sol, com in zip(solvent_free_energy, complex_free_energy):
        free_energy = com - sol
        binding_free_energy.append(free_energy)
    return binding_free_energy


def constraint(mutant_parameters, net_charge):
    sum_ = net_charge
    for charge in mutant_parameters:
        sum_ = sum_ - charge
    return sum_

